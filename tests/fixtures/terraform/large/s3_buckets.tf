# S3 Buckets for Large Configuration
# Multiple buckets with comprehensive configurations

# Data Lake Buckets
resource "aws_s3_bucket" "data_lake_raw" {
  bucket = "${local.name_prefix}-data-lake-raw"

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-data-lake-raw"
    Purpose     = "data-lake"
    DataTier    = "raw"
    Sensitivity = "confidential"
  })
}

resource "aws_s3_bucket" "data_lake_processed" {
  bucket = "${local.name_prefix}-data-lake-processed"

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-data-lake-processed"
    Purpose     = "data-lake"
    DataTier    = "processed"
    Sensitivity = "confidential"
  })
}

resource "aws_s3_bucket" "data_lake_curated" {
  bucket = "${local.name_prefix}-data-lake-curated"

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-data-lake-curated"
    Purpose     = "data-lake"
    DataTier    = "curated"
    Sensitivity = "confidential"
  })
}

# Application Buckets
resource "aws_s3_bucket" "app_assets" {
  bucket = "${local.name_prefix}-app-assets"

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-app-assets"
    Purpose = "application-assets"
  })
}

resource "aws_s3_bucket" "app_uploads" {
  bucket = "${local.name_prefix}-app-uploads"

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-app-uploads"
    Purpose = "user-uploads"
  })
}

# Logging and Audit Buckets
resource "aws_s3_bucket" "access_logs" {
  bucket = "${local.name_prefix}-access-logs"

  tags = merge(local.common_tags, {
    Name       = "${local.name_prefix}-access-logs"
    Purpose    = "logging"
    Compliance = "audit"
  })
}

resource "aws_s3_bucket" "cloudtrail_logs" {
  bucket = "${local.name_prefix}-cloudtrail-logs"

  tags = merge(local.common_tags, {
    Name       = "${local.name_prefix}-cloudtrail-logs"
    Purpose    = "audit"
    Compliance = "required"
  })
}

resource "aws_s3_bucket" "vpc_flow_logs" {
  bucket = "${local.name_prefix}-vpc-flow-logs"

  tags = merge(local.common_tags, {
    Name       = "${local.name_prefix}-vpc-flow-logs"
    Purpose    = "network-logging"
    Compliance = "required"
  })
}

# Backup Buckets
resource "aws_s3_bucket" "db_backups" {
  bucket = "${local.name_prefix}-db-backups"

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-db-backups"
    Purpose     = "backup"
    Sensitivity = "critical"
  })
}

resource "aws_s3_bucket" "disaster_recovery" {
  bucket = "${local.name_prefix}-disaster-recovery"

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-disaster-recovery"
    Purpose     = "disaster-recovery"
    Sensitivity = "critical"
  })
}

# Versioning Configurations
resource "aws_s3_bucket_versioning" "data_lake_raw" {
  bucket = aws_s3_bucket.data_lake_raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "data_lake_processed" {
  bucket = aws_s3_bucket.data_lake_processed.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "disaster_recovery" {
  bucket = aws_s3_bucket.disaster_recovery.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Lifecycle Rules
resource "aws_s3_bucket_lifecycle_configuration" "data_lake_raw" {
  bucket = aws_s3_bucket.data_lake_raw.id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "log-retention"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "GLACIER"
    }

    expiration {
      days = 90
    }
  }
}

# Server-Side Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake_raw" {
  bucket = aws_s3_bucket.data_lake_raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# Outputs
output "data_lake_bucket_arns" {
  description = "Data lake bucket ARNs"
  value = {
    raw       = aws_s3_bucket.data_lake_raw.arn
    processed = aws_s3_bucket.data_lake_processed.arn
    curated   = aws_s3_bucket.data_lake_curated.arn
  }
}

output "logging_bucket_arns" {
  description = "Logging bucket ARNs"
  value = {
    access_logs    = aws_s3_bucket.access_logs.arn
    cloudtrail     = aws_s3_bucket.cloudtrail_logs.arn
    vpc_flow_logs  = aws_s3_bucket.vpc_flow_logs.arn
  }
}

output "backup_bucket_arns" {
  description = "Backup bucket ARNs"
  value = {
    db_backups         = aws_s3_bucket.db_backups.arn
    disaster_recovery  = aws_s3_bucket.disaster_recovery.arn
  }
}

