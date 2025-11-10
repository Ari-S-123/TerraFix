resource "aws_s3_bucket" "test_vulnerable" {
  bucket = var.test_bucket_name
  
  tags = {
    Name = "self-healing-test"
  }
}

# Intentionally misconfigured for testing
resource "aws_s3_bucket_public_access_block" "test_vulnerable" {
  bucket = aws_s3_bucket.test_vulnerable.id
  
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

