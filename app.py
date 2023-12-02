from flask import Flask, render_template, jsonify, make_response, request
import requests
import openai
import random
import os
import json
import ijson
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

openai.api_key = os.environ.get("OPENAI_API_KEY")

def scrape_painting():
    api_key = os.environ.get("HARVARD_API_KEY")
    # Only request the fields you need
    fields = 'primaryimageurl,title,people'
    url = f"https://api.harvardartmuseums.org/object?apikey={api_key}&size=100&sort=random&classification=Paintings&hasimage=1&sortorder=asc&fields={fields}"

    try:
        response = requests.get(url)
        logging.info(f"URL: {url}")
        logging.info(f"Response status code: {response.status_code}")

        response.raise_for_status()
        paintings_data = response.json()['records']

        if not paintings_data:
            return {"image_url": "", "title": "Untitled", "artist": "Unknown Artist"}

        painting = random.choice(paintings_data)
        image_url = painting.get("primaryimageurl", "")
        title = painting.get("title", "Untitled")
        
        # Fetch the artist's name; assume there's at least one artist entry
        artist_name = "Unknown Artist"
        if 'people' in painting and painting['people']:
            artist_info = painting['people'][0]
            # Check if 'name' is not None before assigning
            if artist_info.get('name') is not None:
                artist_name = artist_info['name']

        return {
            "image_url": image_url,
            "title": title,
            "artist": artist_name
        }
    except requests.exceptions.RequestException as e:
        logging.error(f"Request to Harvard API failed: {e}")
        return {"image_url": "", "title": "Untitled", "artist": "Unknown Artist"}


# Updated generate_artwork_info function with full functionality and logging
def generate_artwork_info(artist, title, image_url):
    try:
        visual_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this painting, focusing on its most notable visual aspects. Be short and concise, max 2 sentences"},
                        {"type": "image_url", "image_url": image_url},
                    ]
                }
            ],
            max_tokens=150
        )
        visual_text = visual_response.choices[0].message["content"]
        prompts = [
            f"The painting '{title}' by {artist} features {visual_text}. What historical narratives or emotions might these details suggest? Be short, touching, and concise (max 2 sentences)",
        ]
        prompt = random.choice(prompts)
        text_response = openai.ChatCompletion.create(
            model="gpt-4-1106-preview",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable and articulate art historian."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=230
        )
        text = text_response.choices[0].message["content"]
        combined_text = f"VISUAL_MARKER{visual_text}HISTORICAL_MARKER{text}"

        logging.info(f"Generated Artwork Info: {combined_text}")
        return combined_text.strip()
    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error: {e}")
        return "An error occurred while processing the image. Please try again later."
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return "An unexpected error occurred. Please try again later."

@app.route('/')
def home():
    # Renders the basic structure of the page without detailed painting interpretation
    return render_template('index.html')

@app.route('/interpretation')
def interpretation():
    painting = scrape_painting()
    if painting is None:
        return jsonify({"error": "Unable to fetch painting"})
    painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["image_url"])
    painting["info"] = painting_info
    return jsonify(painting)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

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
