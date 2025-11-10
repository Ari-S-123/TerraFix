resource "aws_lambda_function" "remediation_orchestrator" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = var.lambda_function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.12"
  timeout          = 300
  memory_size      = 512
  
  layers = [aws_lambda_layer_version.dependencies.arn]
  
  environment {
    variables = {
      DYNAMODB_TABLE    = aws_dynamodb_table.remediation_history.name
      BEDROCK_MODEL_ID  = var.bedrock_model_id
      AWS_REGION        = var.aws_region
      LOG_LEVEL         = var.log_level
      DRY_RUN           = var.dry_run
    }
  }
  
  tags = {
    Name        = "self-healing-cloud"
    Environment = "hackathon"
  }
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 7
}

