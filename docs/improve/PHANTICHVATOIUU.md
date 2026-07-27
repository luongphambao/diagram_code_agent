# HLAS Digital Underwriting Platform — Phân tích & tối ưu kiến trúc

**Bản gốc:** `diagram 18.drawio` (1 trang, 1835×1578) · **Bản mới:** `HLAS-Underwriting-Architecture-v2.drawio` (4 trang)
Ngày: 26/07/2026 · Vai trò: Solution Architect review

---

## 1. Đánh giá bản gốc — 12 vấn đề tìm được

Tôi parse trực tiếp XML của file gốc để có số liệu, không đánh giá bằng cảm tính.

| # | Vấn đề | Bằng chứng trong file gốc | Mức độ |
|---|---|---|---|
| 1 | **Component "trôi nổi", không có quan hệ** | 40 component nhưng chỉ **16 edge**. Toàn bộ zone Data (SQL Server, Redis, Reporting Mart, Policy Vault, Elasticsearch) gần như không có edge nào chỉ ra *ai đọc/ghi*. Backup, CI/CD, Grafana, MLflow, secrets vault cũng vậy. | 🔴 Nghiêm trọng |
| 2 | **Nhãn edge là placeholder, không mang nghĩa** | `"governed APIs (×2 flows)"`, `"systems sync (×3 flows)"`, `"Core data sync (all layers)"`, `"Credentials (all layers)"`. Đây là chuỗi sinh tự động, không phải hợp đồng interface. Người đọc không biết protocol, auth, chiều, tần suất. | 🔴 Nghiêm trọng |
| 3 | **Edge sai về mặt kiến trúc** | `nginx → keycloak` nối *bottom-to-bottom* với nhãn "governed APIs" — Nginx không gọi Keycloak. `ai_services → audit_service` gán nhãn `"document intake"`. `sql_server → elastic_search` nối trực tiếp (thực tế phải qua CDC/indexer). | 🔴 Nghiêm trọng |
| 4 | **Dùng icon AWS cho một kiến trúc "no cloud"** | 17 shape `mxgraph.aws4.*` (`rds_sql_server_instance`, `ec2_aws_microservice_extractor_for_net`, `application_load_balancer`…) trong khi chính diagram ghi *"Singapore datacenter; no cloud PII"*. Trước ARB, đây là mâu thuẫn tự phá uy tín. | 🔴 Nghiêm trọng |
| 5 | **Icon gán sai sản phẩm** | `elastic_search__ic` là một logo "S" màu xanh — không phải Elasticsearch. `b2b_portal__ic` cũng vậy. | 🟠 Cao |
| 6 | **Routing đi lòng vòng vô nghĩa** | `document_service → rabbitmq` có waypoint `(1398,161) → (261,161) → (261,536) → (154,536)` — vòng qua toàn bộ chiều rộng trang để nối 2 node cách nhau 1 zone. | 🟠 Cao |
| 7 | **Không có luồng nghiệp vụ** | Không có thứ tự bước, không có decision point, không có SLA. Người đọc không trả lời được: *"một đơn bảo hiểm đi qua hệ thống này thế nào, ở đâu thì máy quyết, ở đâu thì người quyết?"* | 🟠 Cao |
| 8 | **Layout mâu thuẫn với chú thích** | Banner ghi thứ tự `CHANNELS → ON-PREM → DMZ → APP → INTEGRATION → AI → SECURITY`, nhưng zone `1 · USERS` nằm ở **góc phải ngoài cùng** (x=1567) còn `2 · CHANNELS` ở góc trái (x=40). Mắt phải nhảy qua lại. | 🟠 Cao |
| 9 | **"HLAS On-Premises Boundary" là một cái box, không phải boundary** | Nó là 1 card 200×78 nằm cạnh các card khác, thay vì là container bao quanh DMZ/App/Data/Integration. Vì vậy diagram **không thể hiện được trust boundary** — thứ quan trọng nhất với MAS/PDPA. | 🔴 Nghiêm trọng |
| 10 | **Legend không khớp thực tế** | Footer khai báo 4 loại đường (`Control/access`, `Core execution`, `Request/data flow`, `Monitoring/telemetry`) nhưng edge thực tế chỉ dùng 2–3 màu và không map được vào 4 loại đó. | 🟡 Trung bình |
| 11 | **Note rỗng nghĩa** | `"Target outcome — Consumers act on these results."` là filler, chiếm chỗ mà không thêm thông tin. | 🟡 Trung bình |
| 12 | **Thiếu toàn bộ tầng "chứng minh"** | Không có NFR/SLO, không có RPO/RTO, không có node count/sizing, không có firewall matrix, không có interface register, không có ADR, không có assumption/risk, không có document control. Đây chính là những thứ ARB sẽ hỏi. | 🟠 Cao |

**Kết luận:** bản gốc là một *component inventory* được vẽ đẹp, chưa phải một *architecture diagram*. Nó trả lời "có những gì" nhưng không trả lời "ghép với nhau ra sao, tại sao, và có an toàn/đủ tin cậy không".

---

## 2. Nguyên tắc thiết kế đã áp dụng

1. **Tách theo mức trừu tượng (C4-style)** — 1 trang cho lãnh đạo, 1 trang cho kiến trúc, 1 trang cho luồng nghiệp vụ, 1 trang cho bằng chứng vận hành. Một trang không thể vừa "dễ hiểu trong 30 giây" vừa "đủ chi tiết để build".
2. **Mọi đường kẻ là một hợp đồng.** Màu + kiểu nét mã hoá *loại hợp đồng* (đồng bộ / bất đồng bộ / truy cập dữ liệu / control plane / telemetry / vượt biên giới tin cậy / batch), không mã hoá transport. Mỗi connector trên trang 2 đều có một dòng tương ứng trong **Interface Register** ở trang 4 với owner đích danh.
3. **Trust boundary là container, không phải box.** Toàn bộ zone 2–8 nằm trong khung nét đứt "HLAS On-Premises Trust Boundary". Mọi lời gọi ra ngoài đều đi xuống, xuyên qua một **dải "Outbound trust-boundary crossing"** với marker ổ khoá tại từng điểm cắt.
4. **Không có component trôi nổi.** Mọi node đều có ít nhất một quan hệ vào/ra. Những mối quan hệ cross-cutting (Vault → mọi service; OTel → mọi zone) được vẽ thành **2 "rail" dọc** có nhãn, thay vì 30 mũi tên rối.
5. **Zone đánh số theo thứ tự request.** 1 Channels → 2 Edge/DMZ → 3 Application → 4 Platform → 5 AI → 6 Data → 7 Ops → 8 Integration → 9 External. Có strip "How to read this diagram" ở đầu trang.
6. **Layout theo grid có hành lang dành riêng.** Toàn bộ toạ độ sinh từ code, có "reserved corridor" (x=1138) để đường dài đi xuyên band mà không cắt qua card. Nhãn đều có halo trắng nên không bị đường kẻ xuyên chữ.
7. **Icon trung thực.** Chỉ dùng logo vendor khi đúng sản phẩm (Nginx, Keycloak, Redis, RabbitMQ, MinIO, MLflow, GitLab, Prometheus, Grafana, Vault, IBM, Microsoft). Còn lại dùng một bộ **35 glyph hình học tự vẽ, cùng một stroke weight** — in đen trắng vẫn đọc được. **Bỏ 100% icon AWS.**
8. **Nói rõ điều chưa biết.** Có panel Risks, Open assumptions, Decisions needed from this board. Kiến trúc trung thực về khoảng trống của nó đáng tin hơn kiến trúc trông như đã hoàn hảo.

---

## 3. Bốn trang — nội dung và mục đích

### Trang 1 — System Context (2400×1376)
*Dùng cho: 10 phút đầu buổi họp, cho CTO/business.*
- Khối trung tâm = 8 capability nghiệp vụ mà platform **sở hữu**, mỗi cái kèm một chỉ số đo được.
- 5 actor bên trái, 6 external dependency bên phải, mỗi edge ghi rõ protocol + auth + chiều.
- Panel "Not owned by this platform" — chống scope creep.
- Bảng **Business outcomes**: hiện tại → mục tiêu → cơ sở (ví dụ straight-through 15% → 70%).
- Panel **Decisions needed from this board** với người phải quyết (CUO, CRO, CISO/DPO, Head of Core Systems…).

### Trang 2 — Container Architecture (2400×1820) — trang thay thế diagram cũ
*Dùng cho: phần kỹ thuật chính.*
- 9 zone, ~45 container, mỗi card có: tên · tech stack · sizing · badge resilience.
- 65 edge **có nhãn thật**: `OIDC / JWT`, `EF Core · TDS 1.4`, `PDF/A + object lock`, `CDC → index`, `outbound integration jobs`, `tokenised payment authorisation`…
- Integration Gateway fan-out ra 5 adapter, 5 adapter cắt boundary xuống 5 external system — **thẳng hàng dọc**, mỗi điểm cắt có marker.
- 2 rail cross-cutting: control plane (Vault) đi lên, telemetry plane (OTel) đi xuống.
- Panel: NFR targets · Security & trust controls · Resilience posture · Environments & release path · **7 ADR** · Risks & open items · Document control (có cả changelog so với v1.3).

### Trang 3 — Primary Underwriting Flow (2400×1510)
*Dùng cho: thuyết phục business rằng nghiệp vụ đúng, và thuyết phục risk rằng AI được kiểm soát.*
- **15 bước có số**, 7 swimlane, chạy trái → phải.
- Ribbon **time budget**: bước 1–10 ≤ 8s tự động · bước 11–12 ≤ 4 giờ làm việc · bước 13 ≤ 15 phút.
- **Decision gate (bước 10)** làm nổi bật, có 2 nhánh: `auto-accept within authority — target 70%` và `refer ≈ 30%`.
- **Đường ngoại lệ nét đứt đỏ**: AI timeout/confidence thấp → underwriting tay; AML hit → bắt buộc compliance referral.
- Đóng vòng: bước 14 → "Policy pack delivered" trở về lane khách hàng.
- Bảng **step-level**: mỗi bước có Key control · Evidence written · Budget.
- Bảng **authority matrix**: risk band × sum insured → decision path → approval (single / four-eyes).
- Panel **Exception & compensation paths**: 7 tình huống lỗi kèm hành vi bù trừ.

### Trang 4 — Deployment, Security & Governance (2400×1522)
*Dùng cho: câu hỏi khó của Security / Ops / Audit.*
- **Topology 2 room** trên một campus, dark fibre ≤ 2 ms, sync commit, quorum vote.
- **Node inventory** 18 dòng: Room A / Room B / sizing / failover mode.
- **Interface Register** 18 dòng (I-01…I-18): interface · protocol & auth · direction · frequency/SLA · **owner**. Đây là thứ khiến trang 2 "explainable" mà không cần nhãn dài.
- **Firewall matrix** zone-to-zone, default deny, có rule owner.
- **Data classification** × encryption at rest / in transit × retention × deletion path.
- **AI & model governance lifecycle** 7 giai đoạn: Propose → Train → Validate → Approve → Deploy → Monitor → Retire, kèm 5 nguyên tắc cứng (AI không bao giờ tự bind policy).
- **Backup / DR / Go-live readiness gates** với trạng thái xanh–vàng.

---

## 4. Giả định tôi đã đặt — cần bạn xác nhận hoặc sửa

Diagram gốc không có các thông tin này; tôi điền giá trị hợp lý theo bối cảnh một insurer Singapore để bản vẽ *có thể phản biện được*. Nếu số thực khác, sửa trực tiếp trong drawio.

| Nhóm | Giả định đã dùng |
|---|---|
| Volumetrics | 1.200 submission/ngày peak · 6.000 quote/ngày · 9.000 trang tài liệu/ngày · 60 underwriter đồng thời · 180 req/s peak · 35.000 policy renewal/tháng |
| SLO | Availability 99.5% giờ làm việc · P95 quote ≤ 3 s · P95 auto-decision ≤ 8 s · report ≤ 30 s |
| RPO/RTO | SoR: RPO 0 / RTO ≤ 15 phút · Document: ≤ 15 phút / ≤ 1 giờ · Full platform RTO ≤ 4 giờ |
| Straight-through | Hiện tại ~15% → mục tiêu 70% ở tháng 12 |
| Authority matrix | ≤ S$250k auto · S$250k–1m single underwriter · > S$1m four-eyes |
| AI | Confidence floor 0.85 · inference budget 3 s · AI **chỉ advisory**, không tự bind |
| Sizing | API 2× 4 vCPU/16 GB · SQL Server 16 vCPU/64 GB · AI inference 8 vCPU/32 GB (+GPU option) · MinIO 5 TB usable |
| Regulatory | MAS technology-risk expectations · PDPA · group IT security policy. *Tôi cố ý không trích số hiệu Notice cụ thể* — nếu cần, bạn xác nhận đúng notice trước khi in. |
| AD/LDAP | HLAS Active Directory là directory có thẩm quyền, **ngoài scope platform**, Keycloak federate qua LDAPS |

---

## 5. Cách dùng file

- **`HLAS-Underwriting-Architecture-v2.drawio`** — mở bằng app.diagrams.net hoặc VS Code extension. 4 tab tương ứng 4 trang. Toàn bộ card là group: kéo card thì icon + chữ + accent bar đi theo. Edge đã gắn source/target với exit/entry cố định nên di chuyển node là đường tự bám.
- **4 file PNG** — render ở 2× (ví dụ trang 2 là 4800×3640 px), đủ nét để in A1 hoặc chèn vào slide/Word.
- **4 file SVG** — dùng khi cần vector cho LaTeX/Word hoặc zoom vô hạn.

**Gợi ý trình bày ARB (45 phút):** Trang 1 (10') → Trang 3 (12', kể chuyện một đơn bảo hiểm) → Trang 2 (15') → Trang 4 (5', chỉ mở khi bị hỏi) → Decisions needed (3').

---

## 6. Việc còn nên làm (nếu bạn muốn tôi tiếp)

1. **Sequence diagram** chi tiết cho 2 luồng khó nhất: AI inference với fallback, và AS/400 reconciliation + compensating transaction.
2. **Trang 5 — Roadmap & phasing**: phase 1/2/3, dependency, critical path, mốc go-live.
3. **Threat model (STRIDE)** theo từng trust-boundary crossing đã vẽ ở trang 2.
4. **Data flow diagram cho PDPA** — mapping personal data theo purpose, lawful basis, retention, deletion.
5. **Điền số thật** thay các giả định ở mục 4.
