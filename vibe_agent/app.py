import json
import os
import boto3
import uuid
from datetime import datetime
from decimal import Decimal

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
bedrock_runtime = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-west-2'))

# Environment variables
TABLE_NAME = os.environ.get('VIBE_TABLE_NAME', 'vibeguardian-vibes')
MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')

def lambda_handler(event, context):
    """
    Main Lambda handler for VibeGuardian
    Analyzes message sentiment using AWS Bedrock and stores results
    """
    try:
        # Parse incoming request
        body = json.loads(event.get('body', '{}'))
        message = body.get('message', '')
        user_id = body.get('userId', 'anonymous')
        channel_id = body.get('channelId', 'default')
        
        if not message:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Message is required'})
            }
        
        # Analyze vibe using Bedrock
        vibe_analysis = analyze_vibe_with_bedrock(message)
        
        # Store result in DynamoDB
        message_id = str(uuid.uuid4())
        timestamp = int(datetime.utcnow().timestamp())
        
        table = dynamodb.Table(TABLE_NAME)
        table.put_item(
            Item={
                'messageId': message_id,
                'timestamp': timestamp,
                'userId': user_id,
                'channelId': channel_id,
                'message': message,
                'vibeScore': Decimal(str(vibe_analysis['score'])),
                'sentiment': vibe_analysis['sentiment'],
                'analysis': vibe_analysis['analysis'],
                'createdAt': datetime.utcnow().isoformat()
            }
        )
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'messageId': message_id,
                'vibeScore': vibe_analysis['score'],
                'sentiment': vibe_analysis['sentiment'],
                'analysis': vibe_analysis['analysis'],
                'timestamp': timestamp
            })
        }
        
    except Exception as e:
        print(f"Error processing vibe check: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error', 'details': str(e)})
        }


def analyze_vibe_with_bedrock(message):
    """
    Use AWS Bedrock to analyze the vibe/sentiment of a message
    """
    try:
        prompt = f"""Analyze the vibe and sentiment of the following message. 
Provide a vibe score from 0-100 (where 0 is very negative, 50 is neutral, 100 is very positive),
a sentiment label (positive/neutral/negative), and a brief analysis.

Message: "{message}"

Respond in JSON format:
{{
  "score": <number 0-100>,
  "sentiment": "<positive|neutral|negative>",
  "analysis": "<brief explanation>"
}}"""

        # Call Bedrock API
        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
        )
        
        # Parse response
        result = json.loads(response['body'].read())
        content = result['content'][0]['text']
        
        # Extract JSON from response
        vibe_data = json.loads(content)
        
        return {
            'score': vibe_data.get('score', 50),
            'sentiment': vibe_data.get('sentiment', 'neutral'),
            'analysis': vibe_data.get('analysis', 'Unable to analyze')
        }
        
    except Exception as e:
        print(f"Bedrock analysis error: {str(e)}")
        # Fallback to simple analysis
        return {
            'score': 50,
            'sentiment': 'neutral',
            'analysis': f'Analysis unavailable: {str(e)}'
        }

