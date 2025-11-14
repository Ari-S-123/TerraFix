/**
 * ECS cluster and Fargate service for TerraFix.
 */

resource "aws_ecs_cluster" "terrafix" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_ecs_task_definition" "terrafix" {
  family                   = "${var.project_name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "terrafix"
      image     = "${aws_ecr_repository.terrafix.repository_url}:latest"
      essential = true

      environment = [
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "BEDROCK_MODEL_ID"
          value = var.bedrock_model_id
        },
        {
          name  = "POLL_INTERVAL_SECONDS"
          value = tostring(var.poll_interval_seconds)
        },
        {
          name  = "SQLITE_PATH"
          value = "/tmp/terrafix.db"
        },
        {
          name  = "LOG_LEVEL"
          value = "INFO"
        },
        {
          name  = "GITHUB_REPO_MAPPING"
          value = var.github_repo_mapping
        },
        {
          name  = "TERRAFORM_PATH"
          value = var.terraform_path
        },
        {
          name  = "MAX_CONCURRENT_WORKERS"
          value = "3"
        },
        {
          name  = "STATE_RETENTION_DAYS"
          value = "7"
        }
      ]

      secrets = [
        {
          name      = "VANTA_API_TOKEN"
          valueFrom = aws_secretsmanager_secret.vanta_api_token.arn
        },
        {
          name      = "GITHUB_TOKEN"
          valueFrom = aws_secretsmanager_secret.github_token.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.terrafix.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_ecs_service" "terrafix" {
  name            = "${var.project_name}-${var.environment}"
  cluster         = aws_ecs_cluster.terrafix.id
  task_definition = aws_ecs_task_definition.terrafix.arn
  desired_count   = 1 # Single task for SQLite simplicity
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.terrafix.id]
    assign_public_ip = true # Set to false if using private subnets with NAT
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_security_group" "terrafix" {
  name        = "${var.project_name}-${var.environment}"
  description = "Security group for TerraFix ECS task"
  vpc_id      = var.vpc_id

  # Allow all outbound (for API calls to Vanta, GitHub, Bedrock)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}"
    Environment = var.environment
    Project     = var.project_name
  }
}

