variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "lambda_function_name" {
  description = "Lambda function name"
  type        = string
  default     = "remediation-orchestrator"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table name"
  type        = string
  default     = "remediation-history"
}

variable "test_bucket_name" {
  description = "Test S3 bucket name (must be globally unique)"
  type        = string
}

variable "bedrock_model_id" {
  description = "Bedrock model ID"
  type        = string
  default     = "anthropic.claude-sonnet-4-5-v2:0"
}

variable "log_level" {
  description = "Lambda log level"
  type        = string
  default     = "INFO"
}

variable "dry_run" {
  description = "Dry run mode (true/false)"
  type        = string
  default     = "true"
}

