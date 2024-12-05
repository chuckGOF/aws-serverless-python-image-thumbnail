import os
import uuid
import boto3
import json
from io import BytesIO
from PIL import Image, ImageOps
from datetime import datetime

s3 = boto3.client('s3', region_name=str(os.environ['REGION_NAME']))
size = int(os.environ['THUMBNAIL_SIZE'])
db_table = str(os.environ['DYNAMODB_TABLE'])
dynamodb = boto3.resource('dynamodb', region_name=str(os.environ['REGION_NAME']))


def s3_thumbnail_generator(event, context):
    #parse event
    print("EVENT:::", event)
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    img_size = event['Records'][0]['s3']['object']['size']

    if (not key.endswith('_thumbnail.png')):
        image = get_s3_image(bucket, key)
        thumbnail = image_to_thumbnail(image)
        thumbnail_key = new_filename(key)
        url = upload_to_s3(bucket, thumbnail_key, thumbnail, img_size)

        return url


def get_s3_image(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    image_content = response['Body'].read()
    file = BytesIO(image_content)
    img = Image.open(file)
    return img

def image_to_thumbnail(image):
    return ImageOps.fit(image, (size, size))

def new_filename(key):
    base, ext = key.rsplit('.', 1)
    print(ext)
    return f'{base}_thumbnail.png'

def upload_to_s3(bucket, key, image, img_size):
    out_thumbnail = BytesIO()
    image.save(out_thumbnail, 'PNG')
    out_thumbnail.seek(0)

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=out_thumbnail,
        ContentType='image/png'
    )

    # url = f'{s3.meta.endpoint_url}/{bucket}/{key}'
    url = f'https://{bucket}.s3.amazonaws.com/{key}'

    # save image url to db:
    s3_save_thumbnail_url_to_dynamo(url, img_size)
    return url


def s3_save_thumbnail_url_to_dynamo(url_path, img_size):
    to_int = float(img_size * 0.53) / 1000
    table = dynamodb.Table(db_table)
    response = table.put_item(
        Item={
            'id': str(uuid.uuid4()),
            'url': str(url_path),
            'approxReducedSize': str(to_int) + str(' KB'),
            'createdAt': str(datetime.now()),
            'updatedAt': str(datetime.now())
        }
    )
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(response)
    }


def s3_get_thumbnail(event, context):
    table = dynamodb.Table(db_table)
    response = table.get_item(Key={
        'id': event['pathParameters']['id']
    })
    item = response['Item']
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(item),
        'isBase64Encoded': False
    }


def s3_delete_thumbnail(event, context):
    item_id = event['pathParameters']['id']

    # set the default error response
    response = {
        'statusCode': 500,
        'body': f'An error occured while deleting post {item_id}'
    }

    table = dynamodb.Table(db_table)
    response = table.delete_item(Key={
        'id': item_id
    })

    is_success_response = {
        'deleted': True,
        'itemDeletedId': item_id
    }

    # if 
    if response['ResponseMetadata']['HTTPStatusCode'] == 200:
        response = {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(is_success_response)
        }
    return response

def s3_get_thumbnail_urls(event, context):
    table = dynamodb.Table(db_table)
    response = table.scan()
    data = response['Items']

    # paginate through the results in a loop
    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        data.extend(response['Items'])

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(data)
    }