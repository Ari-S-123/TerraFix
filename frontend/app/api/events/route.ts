/**
 * API route to fetch events from DynamoDB.
 * 
 * This route provides a REST API endpoint for retrieving remediation events
 * from the DynamoDB table. It returns the most recent 50 events sorted by
 * timestamp in descending order.
 * 
 * GET /api/events
 * Returns: { events: RemediationEvent[] }
 */

import { NextResponse } from "next/server";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, ScanCommand } from "@aws-sdk/lib-dynamodb";

const client = new DynamoDBClient({ region: process.env.AWS_REGION || "us-east-1" });
const docClient = DynamoDBDocumentClient.from(client);

/**
 * GET handler for fetching remediation events from DynamoDB.
 * 
 * @returns NextResponse containing an array of remediation events or an error
 */
export async function GET() {
  try {
    const command = new ScanCommand({
      TableName: process.env.DYNAMODB_TABLE_NAME || "remediation-history",
      Limit: 50,
    });

    const response = await docClient.send(command);
    
    // Sort by timestamp descending (most recent first)
    const events = (response.Items || []).sort((a, b) => b.timestamp - a.timestamp);

    return NextResponse.json({ events });
  } catch (error) {
    console.error("Error fetching events:", error);
    return NextResponse.json(
      { error: "Failed to fetch events" },
      { status: 500 }
    );
  }
}

