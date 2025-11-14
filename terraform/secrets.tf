/**
 * AWS Secrets Manager secrets for TerraFix credentials.
 */

resource "aws_secretsmanager_secret" "vanta_api_token" {
  name        = "${var.project_name}-${var.environment}-vanta-token"
  description = "Vanta OAuth token for TerraFix"

  tags = {
    Name        = "${var.project_name}-${var.environment}-vanta-token"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "vanta_api_token" {
  secret_id     = aws_secretsmanager_secret.vanta_api_token.id
  secret_string = var.vanta_api_token
}

resource "aws_secretsmanager_secret" "github_token" {
  name        = "${var.project_name}-${var.environment}-github-token"
  description = "GitHub personal access token for TerraFix"

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-token"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_secretsmanager_secret_version" "github_token" {
  secret_id     = aws_secretsmanager_secret.github_token.id
  secret_string = var.github_token
}

