output "lambda_function_arn" {
  value = aws_lambda_function.remediation_orchestrator.arn
}

output "event_bus_arn" {
  value = aws_cloudwatch_event_bus.compliance.arn
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.remediation_history.name
}

output "test_bucket_name" {
  value = aws_s3_bucket.test_vulnerable.bucket
}

