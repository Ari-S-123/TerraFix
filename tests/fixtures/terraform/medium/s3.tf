# S3 Buckets for Medium Configuration

resource "aws_s3_bucket" "data_bucket" {
  bucket = "${var.project_name}-data-${var.environment}"

  tags = merge(local.common_tags, {
    Name    = "${var.project_name}-data"
    Purpose = "data-storage"
  })
}

resource "aws_s3_bucket" "logs_bucket" {
  bucket = "${var.project_name}-logs-${var.environment}"

  tags = merge(local.common_tags, {
    Name    = "${var.project_name}-logs"
    Purpose = "logging"
  })
}

resource "aws_s3_bucket" "backup_bucket" {
  bucket = "${var.project_name}-backup-${var.environment}"

  tags = merge(local.common_tags, {
    Name    = "${var.project_name}-backup"
    Purpose = "backup"
  })
}

resource "aws_s3_bucket_versioning" "data_bucket" {
  bucket = aws_s3_bucket.data_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "backup_bucket" {
  bucket = aws_s3_bucket.backup_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

output "data_bucket_arn" {
  value = aws_s3_bucket.data_bucket.arn
}

output "logs_bucket_arn" {
  value = aws_s3_bucket.logs_bucket.arn
}

output "backup_bucket_arn" {
  value = aws_s3_bucket.backup_bucket.arn
}

