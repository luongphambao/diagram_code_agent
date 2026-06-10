/**
 * Stencil resolver — reads stencils_catalog.json (built by Component 1) and
 * resolves a (provider, keyword) pair to a native draw.io stencil style string.
 *
 * Catalog path: STENCIL_CATALOG_PATH env var, else ../../resources/stencils_catalog.json
 * relative to this file (i.e. <repo-root>/resources/stencils_catalog.json).
 */

import { readFile } from "node:fs/promises"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { log } from "./logger.js"

const __dirname = dirname(fileURLToPath(import.meta.url))

// ── Catalog types (mirrors build_stencil_catalog.py output) ─────────────────

interface ProviderEntry {
    library: string
    kind: "resIcon" | "shape" | "image" | "prIcon"
    style: string // template with {shape} and optionally {category}
    shapes?: string[] // flat list (aws, gcp, k8s)
    shapes_by_cat?: Record<string, string[]> // azure2
}

type StencilCatalog = Record<string, ProviderEntry>

// ── Load catalog (once, lazily) ──────────────────────────────────────────────

let catalog: StencilCatalog | null = null
let catalogLoadAttempted = false

async function loadCatalog(): Promise<StencilCatalog | null> {
    if (catalogLoadAttempted) return catalog
    catalogLoadAttempted = true

    const catalogPath =
        process.env.STENCIL_CATALOG_PATH ||
        join(__dirname, "../../resources/stencils_catalog.json")

    try {
        const raw = await readFile(catalogPath, "utf-8")
        catalog = JSON.parse(raw) as StencilCatalog
        const totalProviders = Object.keys(catalog).length
        log.info(`Stencil catalog loaded: ${totalProviders} providers from ${catalogPath}`)
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        log.warn(`Stencil catalog not found at ${catalogPath}: ${msg}`)
        log.warn("Run backend/scripts/build_stencil_catalog.py to generate it.")
        catalog = null
    }

    return catalog
}

// ── Tokenize helper ──────────────────────────────────────────────────────────

function tokenize(s: string): string[] {
    return s
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .trim()
        .split(/\s+/)
        .filter(Boolean)
}

/** All-terms match: every query token must appear in the shape name */
function allTermsMatch(queryTokens: string[], shapeName: string): boolean {
    const shapeTokens = tokenize(shapeName)
    const shapeStr = shapeTokens.join(" ")
    return queryTokens.every((t) => shapeStr.includes(t))
}

// ── Normalize provider key ───────────────────────────────────────────────────

const PROVIDER_ALIASES: Record<string, string> = {
    aws: "aws",
    amazon: "aws",
    aws4: "aws",
    azure: "azure",
    azure2: "azure",
    microsoft: "azure",
    gcp: "gcp",
    gcp2: "gcp",
    google: "gcp",
    googlecloud: "gcp",
    k8s: "k8s",
    kubernetes: "k8s",
    alibaba: "alibabacloud",
    alibabacloud: "alibabacloud",
    ibm: "ibm",
    network: "network",
    cisco: "cisco",
}

function normalizeProvider(provider: string): string {
    const key = provider.toLowerCase().replace(/[^a-z0-9]/g, "")
    return PROVIDER_ALIASES[key] || key
}

// ── Fill style template ──────────────────────────────────────────────────────

function fillStyle(
    entry: ProviderEntry,
    shape: string,
    category?: string,
): string {
    let style = entry.style
    style = style.replace(/\{shape\}/g, shape)
    if (category) {
        style = style.replace(/\{category\}/g, category)
    }
    return style
}

// ── Public API ───────────────────────────────────────────────────────────────

export interface StencilMatch {
    style: string
    library: string
    shape: string
    provider: string
    category?: string
}

/**
 * Resolve a (provider, keyword) pair to a native draw.io stencil style.
 * Returns null if the catalog is unavailable or no match found.
 */
export async function resolveStencil(
    provider: string,
    keyword: string,
): Promise<StencilMatch | null> {
    const cat = await loadCatalog()
    if (!cat) return null

    const normalizedProvider = normalizeProvider(provider)
    const entry = cat[normalizedProvider]

    if (!entry) {
        log.warn(`resolveStencil: unknown provider "${provider}" (normalized: "${normalizedProvider}")`)
        return null
    }

    const queryTokens = tokenize(keyword)
    if (!queryTokens.length) return null

    // Flat shapes list (aws, gcp, k8s)
    if (entry.shapes) {
        const match = entry.shapes.find((s) => allTermsMatch(queryTokens, s))
        if (match) {
            return {
                style: fillStyle(entry, match),
                library: entry.library,
                shape: match,
                provider: normalizedProvider,
            }
        }
    }

    // Category-grouped shapes (azure2)
    if (entry.shapes_by_cat) {
        for (const [cat_name, shapes] of Object.entries(entry.shapes_by_cat)) {
            const match = shapes.find((s) => allTermsMatch(queryTokens, s))
            if (match) {
                return {
                    style: fillStyle(entry, match, cat_name),
                    library: entry.library,
                    shape: match,
                    provider: normalizedProvider,
                    category: cat_name,
                }
            }
        }
    }

    log.debug(`resolveStencil: no match for provider="${normalizedProvider}" keyword="${keyword}"`)
    return null
}

/**
 * Search for stencil matches (returns up to `limit` results).
 * Useful when resolveStencil misses but a fuzzy search is needed.
 */
export async function searchStencils(
    query: string,
    providerFilter?: string,
    limit = 10,
): Promise<StencilMatch[]> {
    const cat = await loadCatalog()
    if (!cat) return []

    const queryTokens = tokenize(query)
    if (!queryTokens.length) return []

    const results: StencilMatch[] = []
    const providerNorm = providerFilter ? normalizeProvider(providerFilter) : undefined

    for (const [providerKey, entry] of Object.entries(cat)) {
        if (providerNorm && providerKey !== providerNorm) continue

        if (entry.shapes) {
            for (const shape of entry.shapes) {
                if (allTermsMatch(queryTokens, shape)) {
                    results.push({
                        style: fillStyle(entry, shape),
                        library: entry.library,
                        shape,
                        provider: providerKey,
                    })
                    if (results.length >= limit) return results
                }
            }
        }

        if (entry.shapes_by_cat) {
            for (const [cat_name, shapes] of Object.entries(entry.shapes_by_cat)) {
                for (const shape of shapes) {
                    if (allTermsMatch(queryTokens, shape)) {
                        results.push({
                            style: fillStyle(entry, shape, cat_name),
                            library: entry.library,
                            shape,
                            provider: providerKey,
                            category: cat_name,
                        })
                        if (results.length >= limit) return results
                    }
                }
            }
        }
    }

    return results
}
