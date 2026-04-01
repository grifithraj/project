import requests

url = 'http://127.0.0.1:8000/detect'
image_path = 'test_image.jpg' # Put a picture of a dog or a person here!

with open(image_path, 'rb') as img:
    files = {'file': (image_path, img, 'image/jpeg')}
    response = requests.post(url, files=files)

print(response.json())