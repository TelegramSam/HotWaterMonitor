import boto3
import json

print('Loading function')
cloudwatch = boto3.client('cloudwatch')


def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': err.message if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
        },
        'isBase64Encoded': False
    }


def lambda_handler(event, context):
    '''Hanldes the inbound update request
    '''
    print("Received event: " + json.dumps(event, indent=2))

    # log values to cloudwatch
    payload = json.loads(event['body'])
    
    metrics = payload["state"]["reported"]
    
    if metrics['device_id'] != 3512530: 
        print("Event from test device. Discarding.");
        return respond(None, {'success':True, 'test':True})
    
    cw_response = cloudwatch.put_metric_data(
        Namespace="HotWater",
        MetricData=[
            {
                'MetricName': 'liters_used',
                'Value': metrics["liters_used"],
                'Unit': 'Count',
                'StorageResolution': 1
            },{
                'MetricName': 'input_degrees_c',
                'Value': metrics["input_degrees_c"],
                'StorageResolution': 1
            },{
                'MetricName': 'output_degrees_c',
                'Value': metrics["output_degrees_c"],
                'StorageResolution': 1
            },{
                'MetricName': 'liter_deficit',
                'Value': metrics["liter_deficit"],
                'StorageResolution': 1
            },{
                'MetricName': 'measured_input_c',
                'Value': metrics["measured_input_c"],
                'StorageResolution': 1
            },{
                'MetricName': 'measured_output_c',
                'Value': metrics["measured_output_c"],
                'StorageResolution': 1
            }
        ])
    
    print("CW Response: " + json.dumps(cw_response, indent=2))

    return respond(None, {'success':True})
