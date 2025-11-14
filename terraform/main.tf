/**
 * TerraFix ECS/Fargate Infrastructure
 *
 * Provisions AWS infrastructure for running TerraFix as a long-running
 * Fargate service with CloudWatch logging and Secrets Manager integration.
 */

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Data sources
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

