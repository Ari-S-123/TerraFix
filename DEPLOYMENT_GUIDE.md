# Deployment Guide

This guide walks you through deploying the Self-Healing Cloud system step-by-step.

## Prerequisites Checklist

- [ ] AWS Account with administrator access
- [ ] AWS CLI installed and configured (`aws configure`)
- [ ] Terraform >= 1.0 installed
- [ ] Node.js >= 18 installed
- [ ] Python 3.12 installed
- [ ] Git installed

## Step 1: Enable Amazon Bedrock Access

**Time: 5-10 minutes (may require AWS approval)**

1. Log into AWS Console
2. Navigate to **Amazon Bedrock** service (us-east-1 region)
3. Go to **Model access** in the left sidebar
4. Click **Request model access**
5. Find **Anthropic > Claude Sonnet 4.5** and click **Request access**
6. Wait for approval (usually instant, but can take up to 24 hours)

**Verify access:**
```bash
aws bedrock list-foundation-models --region us-east-1 --by-provider anthropic
```

You should see `anthropic.claude-sonnet-4-5-v2:0` in the list.

## Step 2: Clone and Setup

```bash
# Clone repository (or navigate to your project directory)
cd Self-Healing-Cloud

# Verify project structure
ls -la
# Should see: backend/, frontend/, terraform/, events/, docs/
```

## Step 3: Deploy AWS Infrastructure

**Time: 5-10 minutes**

```bash
# Navigate to terraform directory
cd terraform

# Initialize Terraform
terraform init

# Generate unique bucket name
export BUCKET_SUFFIX=$(uuidgen | cut -c1-8 | tr '[:upper:]' '[:lower:]')

# Create terraform.tfvars
cat > terraform.tfvars <<EOF
aws_region       = "us-east-1"
test_bucket_name = "self-healing-test-${BUCKET_SUFFIX}"
dry_run          = "true"
log_level        = "INFO"
EOF

# Review planned changes
terraform plan

# Deploy infrastructure
terraform apply -auto-approve

# Save outputs for frontend configuration
terraform output -json > outputs.json
```

**Expected Resources Created:**
- 1 Lambda function (remediation-orchestrator)
- 1 Lambda layer (dependencies)
- 1 EventBridge custom bus (compliance-events)
- 1 EventBridge rule (compliance-failure-rule)
- 1 DynamoDB table (remediation-history)
- 1 S3 bucket (test-vulnerable)
- 1 IAM role + policy
- 1 CloudWatch Log Group

**Verify deployment:**
```bash
# Check Lambda exists
aws lambda get-function --function-name remediation-orchestrator

# Check DynamoDB table
aws dynamodb describe-table --table-name remediation-history

# Check S3 bucket (should have public access disabled = false)
aws s3api get-public-access-block --bucket self-healing-test-${BUCKET_SUFFIX}
```

## Step 4: Configure Frontend

**Time: 5 minutes**

```bash
# Navigate to frontend directory
cd ../frontend

# Install dependencies
npm install

# Extract Terraform outputs
cd ../terraform
export TEST_BUCKET=$(terraform output -raw test_bucket_name)
cd ../frontend

# Create environment configuration
cat > .env.local <<EOF
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)

# Resource Names
DYNAMODB_TABLE_NAME=remediation-history
EVENT_BUS_NAME=compliance-events
TEST_BUCKET_NAME=${TEST_BUCKET}
EOF

# Verify environment file
cat .env.local
```

**Important:** The `.env.local` file contains credentials and should never be committed to version control.

## Step 5: Launch Frontend

**Time: 2 minutes**

```bash
# Start development server
npm run dev
```

Frontend should be running at: **http://localhost:3000**

Open your browser and verify the dashboard loads.

## Step 6: Test the System

**Time: 2 minutes**

### Option A: Test via Dashboard (Recommended)

1. Open http://localhost:3000
2. Click **"🚀 Trigger Test Event"** button
3. Wait 2-5 seconds
4. Event should appear in the table below
5. Check that status shows "success" and action indicates "dry run"

### Option B: Test via AWS CLI

```bash
# Navigate to project root
cd ..

# Update test event with your bucket name
sed -i.bak "s/self-healing-test-xxxxx/${TEST_BUCKET}/g" events/vanta_test_failure.json

# Send test event
aws events put-events --entries file://events/vanta_test_failure.json

# Watch Lambda logs in real-time
aws logs tail /aws/lambda/remediation-orchestrator --follow
```

**Expected Log Output:**
```
Step 1: Invoking Bedrock...
Invoking anthropic.claude-sonnet-4-5-v2:0
Diagnosis: S3 bucket lacks Block Public Access controls...
Step 2: Executing remediation...
[DRY RUN] Would enable BPA for self-healing-test-xxxxx
Step 3: Storing history...
```

### Verify Results

```bash
# Check DynamoDB for event
aws dynamodb scan --table-name remediation-history --limit 1

# Verify bucket state (should still be vulnerable since dry_run=true)
aws s3api get-public-access-block --bucket ${TEST_BUCKET}
```

## Step 7: Enable Live Remediation (Optional)

**Warning:** This will make actual changes to AWS resources.

```bash
cd terraform

# Update terraform.tfvars
sed -i.bak 's/dry_run = "true"/dry_run = "false"/' terraform.tfvars

# Apply changes
terraform apply -auto-approve

# Trigger test event again
cd ..
aws events put-events --entries file://events/vanta_test_failure.json

# Wait 5 seconds, then verify bucket is now protected
aws s3api get-public-access-block --bucket ${TEST_BUCKET}
```

**Expected Output (after live remediation):**
```json
{
    "PublicAccessBlockConfiguration": {
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }
}
```

## Troubleshooting

### Issue: "Access Denied" when invoking Bedrock

**Solution:**
1. Verify model access is enabled in AWS Console
2. Check IAM permissions for Lambda role
3. Ensure you're using us-east-1 region

```bash
aws bedrock list-foundation-models --region us-east-1 | grep claude-sonnet-4-5
```

### Issue: Frontend shows "Failed to fetch events"

**Solution:**
1. Verify AWS credentials in `.env.local`
2. Check DynamoDB table exists
3. Test credentials:

```bash
aws sts get-caller-identity
aws dynamodb scan --table-name remediation-history
```

### Issue: EventBridge not triggering Lambda

**Solution:**
1. Verify event pattern matches:

```bash
aws events test-event-pattern \
  --event-pattern '{"source":["vanta.compliance"],"detail-type":["Test Failed"]}' \
  --event file://events/vanta_test_failure.json
```

2. Check Lambda permissions:

```bash
aws lambda get-policy --function-name remediation-orchestrator
```

### Issue: Terraform apply fails with "bucket already exists"

**Solution:**
```bash
# Generate new unique bucket name
export BUCKET_SUFFIX=$(uuidgen | cut -c1-8 | tr '[:upper:]' '[:lower:]')
echo "test_bucket_name = \"self-healing-test-${BUCKET_SUFFIX}\"" >> terraform/terraform.tfvars

terraform apply -auto-approve
```

## Verification Checklist

- [ ] Terraform applied successfully (no errors)
- [ ] Lambda function exists and has Bedrock permissions
- [ ] DynamoDB table created
- [ ] S3 test bucket created (vulnerable state)
- [ ] EventBridge rule created
- [ ] Frontend starts without errors
- [ ] Dashboard loads at http://localhost:3000
- [ ] Test event triggers successfully
- [ ] Event appears in dashboard table
- [ ] DynamoDB contains event record
- [ ] Lambda logs show Bedrock invocation

## Next Steps

1. **Review the demo script**: See `docs/DEMO_SCRIPT.md` for a 5-minute demo walkthrough
2. **Explore the dashboard**: Monitor real-time events and metrics
3. **Test different scenarios**: Create custom test events in `events/` directory
4. **Add more remediations**: Extend `backend/src/remediation.py` with new resource types
5. **Enable live mode**: Set `dry_run = "false"` for actual remediation

## Cleanup

When you're done testing:

```bash
# Destroy all AWS resources
cd terraform
terraform destroy -auto-approve

# Stop frontend
# Press Ctrl+C in the terminal running npm
```

## Cost Management

**Estimated costs for testing (1 day):**
- Lambda: $0.01
- DynamoDB: $0.01
- Bedrock: $0.10 (10-20 test events)
- EventBridge: $0.00 (free tier)
- S3: $0.00

**Total: ~$0.12/day**

To minimize costs:
1. Destroy resources when not testing (`terraform destroy`)
2. Use dry_run mode by default
3. Set Lambda timeout to minimum required
4. Use DynamoDB on-demand billing

## Support

- **Documentation**: See `README.md` for full documentation
- **Troubleshooting**: See `docs/TROUBLESHOOTING.md` for detailed solutions
- **Architecture**: See `PLAN.md` for system design details

---

**Ready to deploy?** Start with Step 1 above!

