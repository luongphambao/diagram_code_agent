"""
Generate a sample AWS architecture diagram using the Gemini image-generation API.

Docs: https://ai.google.dev/gemini-api/docs/image-generation

The API key is read from the GEMINI_API_KEY environment variable -- it is
intentionally NOT hardcoded here so it can't end up committed to git.
Run with:
    GEMINI_API_KEY=<your key> python generate_image.py
"""

import base64
import os
import sys

from google import genai

MODEL = "gemini-3.1-flash-image"
OUTPUT_PATH = "aws_sample_diagram.jpg"

PROMPT = (
    "A clean, professional AWS cloud architecture diagram in the style of official "
    "AWS Architecture Icons, on a white background. Show a 3-tier web application: "
    "a Route 53 DNS icon at the top pointing to a CloudFront CDN, which points to "
    "an Application Load Balancer. The ALB fans out to an Auto Scaling group of "
    "EC2 instances spread across two Availability Zones inside a VPC. The EC2 "
    "instances connect to a Multi-AZ RDS database and to an S3 bucket used for "
    "static assets. Draw a dashed rectangle labeled 'VPC' around the EC2/RDS "
    "components, and two dashed inner rectangles labeled 'Availability Zone A' and "
    "'Availability Zone B'. Use the standard AWS orange/blue color scheme, clear "
    "labels under every icon, and arrows showing traffic flow left-to-right / "
    "top-to-bottom. Make it look like a real solutions-architecture slide."
)


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("Set GEMINI_API_KEY in the environment before running this script.")

    client = genai.Client(api_key=api_key)

    interaction = client.interactions.create(
        model=MODEL,
        input=PROMPT,
        response_format={
            "type": "image",
            "mime_type": "image/png",
            "aspect_ratio": "16:9",
            "image_size": "2K",
        },
    )

    image_data = interaction.output_image.data
    with open(OUTPUT_PATH, "wb") as f:
        f.write(base64.b64decode(image_data))

    print(f"Saved diagram to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
