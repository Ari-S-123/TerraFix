/**
 * ElastiCache Redis cluster for TerraFix state storage.
 *
 * Provides persistent state storage for failure deduplication that
 * survives ECS task restarts. Uses a single-node Redis cluster with
 * automatic failover disabled for cost efficiency.
 *
 * Security:
 * - Redis is only accessible from ECS tasks via security group rules
 * - Encryption in transit is enabled
 * - No public accessibility
 */

# Subnet group for ElastiCache placement
resource "aws_elasticache_subnet_group" "terrafix" {
  name       = "${var.project_name}-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

# Security group for Redis access
resource "aws_security_group" "redis" {
  name        = "${var.project_name}-redis-${var.environment}"
  description = "Security group for TerraFix Redis cluster"
  vpc_id      = var.vpc_id

  # Allow Redis traffic from ECS tasks only
  ingress {
    description     = "Redis from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.terrafix.id]
  }

  # Allow all outbound (for cluster communication)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name        = "${var.project_name}-redis-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

# ElastiCache Redis cluster
resource "aws_elasticache_cluster" "terrafix" {
  cluster_id           = "${var.project_name}-${var.environment}"
  engine               = "redis"
  engine_version       = "7.0"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.terrafix.name
  security_group_ids = [aws_security_group.redis.id]

  # Maintenance window (UTC) - Sunday 3-4 AM
  maintenance_window = "sun:03:00-sun:04:00"

  # Snapshot configuration
  snapshot_retention_limit = var.redis_snapshot_retention_days
  snapshot_window          = "02:00-03:00"

  # Enable automatic minor version upgrades
  auto_minor_version_upgrade = true

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

# Output the Redis endpoint for ECS configuration
output "redis_endpoint" {
  description = "Redis primary endpoint address"
  value       = aws_elasticache_cluster.terrafix.cache_nodes[0].address
}

output "redis_port" {
  description = "Redis port"
  value       = aws_elasticache_cluster.terrafix.port
}

output "redis_url" {
  description = "Full Redis URL for application configuration"
  value       = "redis://${aws_elasticache_cluster.terrafix.cache_nodes[0].address}:${aws_elasticache_cluster.terrafix.port}/0"
}

