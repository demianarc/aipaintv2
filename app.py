from flask import Flask, render_template
from flask import jsonify
import requests
from bs4 import BeautifulSoup
import openai
import random
import os
import json
from flask import make_response
from flask import request
import ijson
import logging



app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Load OpenAI API key from environment variables
openai.api_key = os.environ.get("OPENAI_API_KEY")
API_ENDPOINT = "https://api.openai.com/v1/chat/completions"

def scrape_painting():
    api_key = os.environ.get("HARVARD_API_KEY")
    fields = 'primaryimageurl,title,people,date'
    url = f"https://api.harvardartmuseums.org/object?apikey={api_key}&size=100&sort=random&classification=Paintings&hasimage=1&sortorder=asc&fields={fields}"

    try:
        response = requests.get(url, stream=True)
        logging.info(f"URL: {url}")
        logging.info(f"Response status code: {response.status_code}")

        response.raise_for_status()
        items = ijson.items(response.raw, 'records.item')
        records = list(items)

        if not records:
            return None

        painting = random.choice(records)
        image_url = painting.get("primaryimageurl")
        title = painting.get("title")
        artist = painting["people"][0].get("name") if "people" in painting and painting["people"] else "Unknown artist"
        date = painting.get("dated")

        return {
            "image_url": image_url,
            "title": title,
            "artist": artist,
            "date": date
        }
    except requests.exceptions.RequestException as e:
        logging.error(f"Request to Harvard API failed: {e}")
        return None

# Updated generate_artwork_info function with full functionality and logging
def generate_artwork_info(artist, title, image_url):
    try:
        visual_response = openai.ChatCompletion.create(
            model="gpt-4-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this artwork, focusing on its most notable visual aspects. Be short and concise, max 2 sentences"},
                        {"type": "image_url", "image_url": image_url},
                    ]
                }
            ],
            max_tokens=150
        )
        visual_text = visual_response.choices[0].message["content"]
        prompts = [
            f"The artwork '{title}' by {artist} features {visual_text}. What historical narratives and emotions might these details suggest? Be short, touching, and concise. If possible, can you discuss the emotional undertones and historical context of this piece, and also if possible how its reflect the era and the artist's own journey.(max 3 sentences)",
        ]
        prompt = random.choice(prompts)
        text_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-1106",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable and articulate art historian capable of deep insights into artworks."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=230
        )
        text = text_response.choices[0].message["content"]
        combined_text = f"{visual_text} {text}"

        logging.info(f"Generated Artwork Info: {combined_text}")
        return combined_text.strip()
    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error: {e}")
        return "An error occurred while processing the image. Please try again later."
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return "An unexpected error occurred. Please try again later."

@app.route('/')
def landing_page():
    return render_template('landing.html')

@app.route('/app')
def painting_of_the_day():
    painting = scrape_painting()
    if painting is None:
        painting_info = "Information could not be generated due to an error."
    else:
        painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["image_url"])
    
    painting["info"] = painting_info if painting_info else "Information could not be generated."
    painting_json = json.dumps(painting if painting else {})
    return render_template('index.html', painting=painting, painting_json=painting_json)

@app.route('/refresh')
def refresh():
    painting = scrape_painting()
    painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["image_url"])
    painting["info"] = painting_info
    return jsonify(painting)

@app.after_request
def add_caching_headers(response):
    # Preload the stylesheet
    if request.path == '/':
        response.headers.add('Link', '</static/css/style.css>; rel=preload; as=style')

    # Cache control for static resources
    if request.path.startswith('/static'):
        response.headers['Cache-Control'] = 'public, max-age=31536000'
    elif request.endpoint != 'refresh':
        # Cache dynamic content for a shorter time
        response.headers['Cache-Control'] = 'public, max-age=36000'
    else:
        # No caching for the API responses that fetch new paintings
        response.headers['Cache-Control'] = 'no-store'
    return response

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
