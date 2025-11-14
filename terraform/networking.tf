/**
 * Networking variables for TerraFix ECS deployment.
 *
 * These should be provided by the user or from existing VPC setup.
 */

variable "vpc_id" {
  description = "VPC ID for ECS deployment"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for ECS tasks (public or private with NAT)"
  type        = list(string)
}

