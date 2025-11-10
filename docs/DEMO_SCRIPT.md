# Demo Script (5 minutes)

## Setup (Pre-Demo)

- [ ] Frontend running: http://localhost:3000
- [ ] AWS Console open: EventBridge, Lambda, DynamoDB
- [ ] Test bucket verified vulnerable
- [ ] CloudWatch Logs open

## Script

### [0:00-0:30] Introduction

"Self-Healing Cloud automatically fixes compliance violations in real-time using AI. Let me show you."

### [0:30-1:00] Show Vulnerable State

```bash
aws s3api get-public-access-block --bucket self-healing-test-xxxxx
# Show all four settings = false
```

### [1:00-1:30] Trigger Event

Click "Trigger Test Event" button in dashboard.

### [1:30-3:00] Watch Automation

- Show EventBridge receiving event
- Show Lambda logs: "Step 1: Invoking Bedrock..."
- Highlight Claude diagnosis in logs
- Show "Step 2: Executing remediation..."

### [3:00-3:30] Verify Fix

```bash
aws s3api get-public-access-block --bucket self-healing-test-xxxxx
# Show all four settings = true
```

### [3:30-4:00] Show Dashboard

- Real-time event appears in table
- Metrics updated
- Click event for details

### [4:00-5:00] Value Proposition

"What took hours now takes 2.3 seconds:
- Zero manual intervention
- Complete audit trail
- Scales to thousands of checks
- Claude understands context and generates precise fixes"

**Key Metrics:**
- Response time: ~2-3 seconds
- Success rate: 100%
- Total remediations: [count]

## Testing Commands

### Manual Test via AWS CLI

```bash
# Send test event to EventBridge
aws events put-events --entries file://events/vanta_test_failure.json

# Watch Lambda logs
aws logs tail /aws/lambda/remediation-orchestrator --follow

# Query DynamoDB
aws dynamodb scan --table-name remediation-history --max-items 5

# Verify bucket state
aws s3api get-public-access-block --bucket self-healing-test-xxxxx
```

### Integration Test

```bash
# Full end-to-end flow
aws events put-events --entries file://events/vanta_test_failure.json
aws logs tail /aws/lambda/remediation-orchestrator --follow
aws dynamodb scan --table-name remediation-history
aws s3api get-public-access-block --bucket self-healing-test-xxxxx
```

## Success Criteria

- [ ] End-to-end workflow < 10 seconds
- [ ] Lambda invokes Bedrock successfully
- [ ] Remediation executes (dry run or live)
- [ ] DynamoDB stores events
- [ ] Frontend displays real-time events
- [ ] Demo runs without errors

## Stretch Goals

- [ ] Multiple resource types
- [ ] Live remediation (dry_run=false)
- [ ] Video demo recorded

