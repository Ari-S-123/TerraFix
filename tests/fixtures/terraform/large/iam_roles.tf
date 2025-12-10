# IAM Roles and Policies for Large Configuration
# Comprehensive IAM setup with multiple roles and fine-grained policies

# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.name_prefix}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-ecs-task-execution"
    Purpose = "ecs-execution"
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role (Application)
resource "aws_iam_role" "ecs_task" {
  name = "${local.name_prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-ecs-task"
    Purpose = "ecs-application"
  })
}

# Lambda Execution Role
resource "aws_iam_role" "lambda_execution" {
  name = "${local.name_prefix}-lambda-execution"

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

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-lambda-execution"
    Purpose = "lambda"
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Data Pipeline Role
resource "aws_iam_role" "data_pipeline" {
  name = "${local.name_prefix}-data-pipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "glue.amazonaws.com"
      }
    }]
  })

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-data-pipeline"
    Purpose = "data-processing"
  })
}

resource "aws_iam_role_policy_attachment" "data_pipeline_glue" {
  role       = aws_iam_role.data_pipeline.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# CI/CD Role
resource "aws_iam_role" "cicd" {
  name = "${local.name_prefix}-cicd"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "codebuild.amazonaws.com"
      }
    }]
  })

  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-cicd"
    Purpose = "deployment"
  })
}

# Custom Policies
resource "aws_iam_policy" "s3_data_lake_access" {
  name        = "${local.name_prefix}-s3-data-lake-access"
  description = "Access to data lake S3 buckets"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListBuckets"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.data_lake_raw.arn,
          aws_s3_bucket.data_lake_processed.arn,
          aws_s3_bucket.data_lake_curated.arn,
        ]
      },
      {
        Sid    = "ReadWriteObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          "${aws_s3_bucket.data_lake_raw.arn}/*",
          "${aws_s3_bucket.data_lake_processed.arn}/*",
          "${aws_s3_bucket.data_lake_curated.arn}/*",
        ]
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "secrets_manager_access" {
  name        = "${local.name_prefix}-secrets-manager-access"
  description = "Access to Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = "arn:aws:secretsmanager:*:*:secret:${local.name_prefix}/*"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_policy" "kms_access" {
  name        = "${local.name_prefix}-kms-access"
  description = "Access to KMS keys"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = local.common_tags
}

# Policy Attachments
resource "aws_iam_role_policy_attachment" "ecs_task_s3" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.s3_data_lake_access.arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_secrets" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.secrets_manager_access.arn
}

resource "aws_iam_role_policy_attachment" "ecs_task_kms" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = aws_iam_policy.kms_access.arn
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = aws_iam_policy.s3_data_lake_access.arn
}

resource "aws_iam_role_policy_attachment" "lambda_secrets" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = aws_iam_policy.secrets_manager_access.arn
}

resource "aws_iam_role_policy_attachment" "data_pipeline_s3" {
  role       = aws_iam_role.data_pipeline.name
  policy_arn = aws_iam_policy.s3_data_lake_access.arn
}

# Outputs
output "iam_role_arns" {
  description = "IAM Role ARNs"
  value = {
    ecs_task_execution = aws_iam_role.ecs_task_execution.arn
    ecs_task           = aws_iam_role.ecs_task.arn
    lambda_execution   = aws_iam_role.lambda_execution.arn
    data_pipeline      = aws_iam_role.data_pipeline.arn
    cicd               = aws_iam_role.cicd.arn
  }
}

