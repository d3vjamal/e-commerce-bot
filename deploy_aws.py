import os
import zipfile

import boto3

# ==============================
# Configuration
# ==============================
SOURCE_DIR = "."
ZIP_NAME = "commerce-bot.zip"

S3_BUCKET = "agentcore-commerce-bot"
S3_KEY = f"{ZIP_NAME}"

EXCLUDE_DIRS = {".venv", "__pycache__", "venv", ".git", ".vscode", ".idea"}


# ==============================
# Helper: check if path should be excluded
# ==============================
def is_excluded(path):
    parts = path.split(os.sep)
    return any(part in EXCLUDE_DIRS for part in parts)


# ==============================
# Create zip
# ==============================
def zip_directory(source_dir, zip_name):
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):

            # Remove excluded dirs so os.walk doesn't even go inside them
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                file_path = os.path.join(root, file)

                # Double safety: skip if any excluded dir appears in path
                if is_excluded(file_path):
                    continue

                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)

    print(f"✅ Created zip: {zip_name}")


# ==============================
# Upload to S3
# ==============================
def upload_to_s3(file_path, bucket, key):
    s3 = boto3.client("s3")
    s3.upload_file(file_path, bucket, key)
    print(f"✅ Uploaded to s3://{bucket}/{key}")


# ==============================
# Main
# ==============================
if __name__ == "__main__":
    zip_directory(SOURCE_DIR, ZIP_NAME)
    upload_to_s3(ZIP_NAME, S3_BUCKET, S3_KEY)
