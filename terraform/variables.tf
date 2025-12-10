/**
 * Terraform variables for TerraFix infrastructure.
 */

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "terrafix"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "cpu" {
  description = "Fargate task CPU units (1024 = 1 vCPU)"
  type        = number
  default     = 2048 # 2 vCPU
}

variable "memory" {
  description = "Fargate task memory in MB"
  type        = number
  default     = 4096 # 4 GB
}

variable "vanta_api_token" {
  description = "Vanta OAuth token (stored in Secrets Manager)"
  type        = string
  sensitive   = true
}

variable "github_token" {
  description = "GitHub personal access token (stored in Secrets Manager)"
  type        = string
  sensitive   = true
}

variable "bedrock_model_id" {
  description = "AWS Bedrock Claude model ID"
  type        = string
  default     = "anthropic.claude-sonnet-4-5-v2:0"
}

variable "poll_interval_seconds" {
  description = "Vanta polling interval in seconds"
  type        = number
  default     = 300
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "github_repo_mapping" {
  description = "JSON mapping of resource patterns to GitHub repos"
  type        = string
  default     = "{\"default\": \"\"}"
}

variable "terraform_path" {
  description = "Path within repos to Terraform files"
  type        = string
  default     = "."
}

variable "vpc_id" {
  description = "VPC ID for security groups and networking"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for ECS tasks and ElastiCache"
  type        = list(string)
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_snapshot_retention_days" {
  description = "Number of days to retain Redis snapshots (0 to disable)"
  type        = number
  default     = 1
}

