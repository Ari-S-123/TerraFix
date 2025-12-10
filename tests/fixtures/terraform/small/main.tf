# Small Terraform Configuration for Testing
# This file represents a minimal infrastructure setup for quick tests

terraform {
  required_version = ">= 1.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-west-2"
}

# Simple S3 bucket for testing
resource "aws_s3_bucket" "test_bucket" {
  bucket = "terrafix-test-small-bucket"

  tags = {
    Environment = "test"
    ManagedBy   = "terraform"
    Purpose     = "terrafix-testing"
  }
}

# Basic IAM role
resource "aws_iam_role" "test_role" {
  name = "terrafix-test-small-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = {
    Environment = "test"
    ManagedBy   = "terraform"
  }
}

output "bucket_arn" {
  description = "ARN of the test S3 bucket"
  value       = aws_s3_bucket.test_bucket.arn
}

output "role_arn" {
  description = "ARN of the test IAM role"
  value       = aws_iam_role.test_role.arn
}

