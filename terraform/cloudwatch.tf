/**
 * CloudWatch log group for TerraFix logs.
 */

resource "aws_cloudwatch_log_group" "terrafix" {
  name              = "/ecs/${var.project_name}-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

# CloudWatch alarms for monitoring
resource "aws_cloudwatch_metric_alarm" "task_count" {
  alarm_name          = "${var.project_name}-${var.environment}-task-count"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = "300"
  statistic           = "Average"
  threshold           = "1"
  alarm_description   = "Alert when TerraFix task is not running"
  treat_missing_data  = "breaching"

  dimensions = {
    ClusterName = aws_ecs_cluster.terrafix.name
    ServiceName = aws_ecs_service.terrafix.name
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-task-count"
    Environment = var.environment
    Project     = var.project_name
  }
}

