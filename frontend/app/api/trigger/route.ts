/**
 * API route to trigger test events.
 * 
 * This route provides a REST API endpoint for manually triggering test
 * compliance failure events. It sends events to the EventBridge custom bus
 * which then triggers the Lambda remediation workflow.
 * 
 * POST /api/trigger
 * Returns: { eventId: string }
 */

import { NextResponse } from "next/server";
import { EventBridgeClient, PutEventsCommand } from "@aws-sdk/client-eventbridge";

const client = new EventBridgeClient({ region: process.env.AWS_REGION || "us-east-1" });

/**
 * POST handler for triggering test compliance failure events.
 * 
 * Creates a test event simulating an S3 Block Public Access compliance failure
 * and sends it to the EventBridge custom bus.
 * 
 * @returns NextResponse containing the event ID or an error
 */
export async function POST() {
  try {
    const eventId = `test-${Date.now()}`;
    
    const command = new PutEventsCommand({
      Entries: [
        {
          Source: "vanta.compliance",
          DetailType: "Test Failed",
          Detail: JSON.stringify({
            test_id: "s3_block_public_access",
            test_name: "S3 Bucket Block Public Access",
            severity: "high",
            framework: "SOC2",
            control_id: "CC6.1",
            resource_type: "AWS::S3::Bucket",
            resource_arn: `arn:aws:s3:::${process.env.TEST_BUCKET_NAME}`,
            resource_id: process.env.TEST_BUCKET_NAME,
            failure_reason: "Block Public Access not enabled",
            current_state: {
              BlockPublicAcls: false,
              IgnorePublicAcls: false,
              BlockPublicPolicy: false,
              RestrictPublicBuckets: false,
            },
            required_state: {
              BlockPublicAcls: true,
              IgnorePublicAcls: true,
              BlockPublicPolicy: true,
              RestrictPublicBuckets: true,
            },
          }),
          EventBusName: process.env.EVENT_BUS_NAME || "compliance-events",
        },
      ],
    });

    await client.send(command);

    return NextResponse.json({ eventId });
  } catch (error) {
    console.error("Error triggering event:", error);
    return NextResponse.json(
      { error: "Failed to trigger event" },
      { status: 500 }
    );
  }
}

