resource "aws_cloudwatch_event_bus" "compliance" {
  name = "compliance-events"
  
  tags = {
    Name = "self-healing-cloud"
  }
}

resource "aws_cloudwatch_event_rule" "compliance_failure" {
  name           = "compliance-failure-rule"
  description    = "Trigger Lambda on compliance test failure"
  event_bus_name = aws_cloudwatch_event_bus.compliance.name
  
  event_pattern = jsonencode({
    source      = ["vanta.compliance"]
    detail-type = ["Test Failed"]
  })
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule           = aws_cloudwatch_event_rule.compliance_failure.name
  event_bus_name = aws_cloudwatch_event_bus.compliance.name
  arn            = aws_lambda_function.remediation_orchestrator.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.remediation_orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.compliance_failure.arn
}

