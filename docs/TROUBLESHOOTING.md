# Troubleshooting Guide

## Common Issues and Solutions

### Lambda fails to invoke Bedrock

**Symptoms:**
- Lambda logs show "Access Denied" errors
- Error mentions "bedrock:InvokeModel"

**Solution:**
```bash
# Check model access
aws bedrock list-foundation-models --region us-east-1 | grep claude-sonnet

# Request access via AWS Console:
# Bedrock > Model access > Request model access > Enable Claude Sonnet 4.5
```

**Verification:**
```bash
aws bedrock list-foundation-models --region us-east-1 --by-provider anthropic
```

---

### EventBridge not triggering Lambda

**Symptoms:**
- Events sent but Lambda never executes
- No logs appearing in CloudWatch

**Solution:**
```bash
# Test event pattern matches your event
aws events test-event-pattern \
  --event-pattern '{"source":["vanta.compliance"],"detail-type":["Test Failed"]}' \
  --event file://events/vanta_test_failure.json

# Verify EventBridge rule is enabled
aws events describe-rule --name compliance-failure-rule --event-bus-name compliance-events

# Check Lambda permissions
aws lambda get-policy --function-name remediation-orchestrator
```

---

### DynamoDB access denied

**Symptoms:**
- Lambda logs show DynamoDB access errors
- Events not being stored

**Solution:**
```bash
# Verify table exists
aws dynamodb describe-table --table-name remediation-history

# Check Lambda role permissions
aws iam get-role-policy --role-name remediation-lambda-role --policy-name remediation-lambda-policy

# Test direct write
aws dynamodb put-item --table-name remediation-history \
  --item '{"event_id":{"S":"test-123"},"timestamp":{"N":"1696876800000"}}'
```

---

### Frontend can't fetch events

**Symptoms:**
- Frontend shows loading spinner indefinitely
- Browser console shows 500 errors

**Solution:**
```bash
# Verify AWS credentials in .env.local
aws sts get-caller-identity

# Test DynamoDB access directly
aws dynamodb scan --table-name remediation-history --max-items 1

# Check environment variables
cat frontend/.env.local
```

---

### Terraform apply fails

**Symptoms:**
- "Bucket name already exists" error
- "IAM role name already exists" error

**Solution:**
```bash
# Generate unique bucket name
export RANDOM_SUFFIX=$(uuidgen | cut -c1-8 | tr '[:upper:]' '[:lower:]')
echo "test_bucket_name = \"self-healing-test-${RANDOM_SUFFIX}\"" >> terraform/terraform.tfvars

# If IAM role exists, import it
terraform import aws_iam_role.lambda_role remediation-lambda-role

# Or destroy and recreate
terraform destroy -auto-approve
terraform apply -auto-approve
```

---

### Lambda timeout errors

**Symptoms:**
- Lambda times out after 3 seconds
- "Task timed out" in logs

**Solution:**

Edit `terraform/lambda.tf`:
```hcl
resource "aws_lambda_function" "remediation_orchestrator" {
  timeout = 300  # Increase to 5 minutes
  # ... rest of config
}
```

Then:
```bash
cd terraform
terraform apply
```

---

### Bedrock throttling errors

**Symptoms:**
- "ThrottlingException" in Lambda logs
- Intermittent failures

**Solution:**

Add retry logic to `backend/src/claude_client.py`:
```python
from botocore.config import Config

config = Config(
    retries = {
        'max_attempts': 3,
        'mode': 'adaptive'
    }
)

self.bedrock_client = boto3.client(
    service_name="bedrock-runtime",
    region_name=region,
    config=config
)
```

---

### S3 remediation fails

**Symptoms:**
- "NoSuchBucket" error
- "Access Denied" on S3 operations

**Solution:**
```bash
# Verify bucket exists
aws s3 ls | grep self-healing-test

# Check bucket permissions
aws s3api get-bucket-policy --bucket self-healing-test-xxxxx

# Verify Lambda role has S3 permissions
aws iam get-role-policy --role-name remediation-lambda-role --policy-name remediation-lambda-policy
```

---

### Frontend build fails

**Symptoms:**
- `npm install` fails
- TypeScript compilation errors

**Solution:**
```bash
cd frontend

# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm cache clean --force
npm install

# Check Node version (requires Node 18+)
node --version

# Update npm
npm install -g npm@latest
```

---

## Debugging Commands

### View Lambda Logs

```bash
# Tail logs in real-time
aws logs tail /aws/lambda/remediation-orchestrator --follow

# Get last 50 log events
aws logs tail /aws/lambda/remediation-orchestrator --since 10m

# Filter for errors only
aws logs tail /aws/lambda/remediation-orchestrator --follow --filter-pattern "ERROR"
```

### Test Lambda Directly

```bash
# Invoke Lambda with test event
aws lambda invoke \
  --function-name remediation-orchestrator \
  --payload file://events/vanta_test_failure.json \
  response.json

# View response
cat response.json | jq
```

### Query DynamoDB

```bash
# Scan entire table
aws dynamodb scan --table-name remediation-history

# Get specific item
aws dynamodb get-item \
  --table-name remediation-history \
  --key '{"event_id":{"S":"your-event-id"},"timestamp":{"N":"1696876800000"}}'

# Query by status
aws dynamodb scan \
  --table-name remediation-history \
  --filter-expression "status = :s" \
  --expression-attribute-values '{":s":{"S":"error"}}'
```

---

## Performance Optimization

### Lambda Cold Starts

If experiencing slow cold starts:

1. Increase memory allocation:
```hcl
resource "aws_lambda_function" "remediation_orchestrator" {
  memory_size = 1024  # Increase from 512
}
```

2. Enable provisioned concurrency (costs extra):
```hcl
resource "aws_lambda_provisioned_concurrency_config" "example" {
  function_name                     = aws_lambda_function.remediation_orchestrator.function_name
  provisioned_concurrent_executions = 1
}
```

### DynamoDB Performance

If table is slow:

```bash
# Switch to provisioned capacity for predictable performance
aws dynamodb update-table \
  --table-name remediation-history \
  --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5
```

---

## Getting Help

If you're still experiencing issues:

1. Check CloudWatch Logs for detailed error messages
2. Verify IAM permissions are correct
3. Ensure all environment variables are set
4. Confirm AWS region consistency across all resources
5. Review Terraform state for resource conflicts

For urgent issues, check:
- AWS Service Health Dashboard
- Bedrock service availability
- EventBridge service status

