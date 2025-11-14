/**
 * Terraform outputs for TerraFix infrastructure.
 */

output "ecr_repository_url" {
  description = "ECR repository URL for TerraFix image"
  value       = aws_ecr_repository.terrafix.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.terrafix.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.terrafix.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.terrafix.name
}

output "task_role_arn" {
  description = "ECS task role ARN"
  value       = aws_iam_role.ecs_task.arn
}

output "execution_role_arn" {
  description = "ECS execution role ARN"
  value       = aws_iam_role.ecs_execution.arn
}

