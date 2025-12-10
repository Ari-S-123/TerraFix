# RDS Configuration for Large Setup
# Production-ready database with high availability

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = aws_subnet.database[*].id

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-db-subnet-group"
  })
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name_prefix}-postgres-params"
  family = "postgres15"

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-postgres-params"
  })
}

resource "aws_db_instance" "primary" {
  identifier = "${local.name_prefix}-postgres-primary"

  engine               = "postgres"
  engine_version       = "15.4"
  instance_class       = "db.r6g.large"
  allocated_storage    = 100
  max_allocated_storage = 500
  storage_type         = "gp3"
  storage_encrypted    = true

  db_name  = "application"
  username = "dbadmin"
  password = "CHANGE_ME_IN_PRODUCTION"  # Use Secrets Manager in production

  multi_az               = true
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name

  backup_retention_period = 30
  backup_window          = "03:00-04:00"
  maintenance_window     = "sun:04:00-sun:05:00"

  deletion_protection = true
  skip_final_snapshot = false
  final_snapshot_identifier = "${local.name_prefix}-postgres-final-snapshot"

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  enabled_cloudwatch_logs_exports = [
    "postgresql",
    "upgrade",
  ]

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-postgres-primary"
    Purpose     = "primary-database"
    Sensitivity = "critical"
  })
}

resource "aws_db_instance" "replica" {
  identifier = "${local.name_prefix}-postgres-replica"

  replicate_source_db = aws_db_instance.primary.identifier
  instance_class      = "db.r6g.large"
  storage_encrypted   = true

  vpc_security_group_ids = [aws_security_group.database.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name

  backup_retention_period = 0  # Replicas don't need independent backups
  skip_final_snapshot     = true

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-postgres-replica"
    Purpose     = "read-replica"
    Sensitivity = "critical"
  })
}

# Outputs
output "rds_endpoints" {
  description = "RDS endpoints"
  value = {
    primary_endpoint = aws_db_instance.primary.endpoint
    replica_endpoint = aws_db_instance.replica.endpoint
    primary_arn      = aws_db_instance.primary.arn
    replica_arn      = aws_db_instance.replica.arn
  }
}

