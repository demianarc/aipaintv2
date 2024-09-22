from flask import Flask, render_template
from flask import jsonify
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import random
import os
import json
from flask import make_response
from flask import request
import ijson
import logging
from dotenv import load_dotenv
load_dotenv() 



app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Load OpenAI API key from environment variable
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
API_ENDPOINT = "https://api.openai.com/v1/chat/completions"

def scrape_painting():
    api_key = os.getenv("HARVARD_API_KEY")
    fields = 'primaryimageurl,title,people,dated'
    url = f"https://api.harvardartmuseums.org/object?apikey={api_key}&size=100&sort=random&classification=Paintings&hasimage=1&sortorder=asc&fields={fields}"

    response = requests.get(url)
    logging.info(f"URL: {url}")
    logging.info(f"Response status code: {response.status_code}")

    if response.status_code != 200:
        logging.error("Failed to fetch painting information.")
        return None

    data = response.json()
    if not data['records']:
        logging.error("No records found.")
        return None

    painting = random.choice(data['records'])
    image_url = painting.get("primaryimageurl")
    title = painting.get("title")
    artist_names = [person.get("name", "Unknown artist") for person in painting.get("people", [])]
    artist = ", ".join(artist_names) if artist_names else "Unknown artist"
    dated = painting.get("dated", "Not available")
    
    # Log the fetched image URL
    logging.info(f"Fetched image URL: {image_url}")

    return {
        "image_url": image_url,
        "title": title,
        "artist": artist,
        "dated": dated
    }


# Updated generate_artwork_info function with full functionality and logging
def generate_artwork_info(artist, title, dated, image_url):
    logging.info("Starting generate_artwork_info")
    logging.info(f"Sending image URL to OpenAI: {image_url}")
    
    # Initialize variables to ensure they have a value even if the subsequent API calls fail
    visual_text = "Visual description not available"
    text = "Textual interpretation not available"
    combined_text = ""

    try:
        # Adjusted request to include the image URL correctly
        visual_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this artwork, focusing on its most notable visual aspects. Be short and concise, max 2 sentences"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            max_tokens=150
        )
        # Assume successful response and update visual_text
        visual_text = visual_response.choices[0].message.content.strip()

        prompt = f"The artwork '{title}' by {artist}, created in {dated}, features {visual_text}. What historical narratives and emotions might these details suggest? Be short, touching, and concise. Can you discuss the emotional undertones and historical context of this piece, reflecting the era and the artist's own journey? (max 3 sentences)."
        
        text_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable and articulate art historian capable of deep insights into artworks."
                },
                {
                    "role": "system",
                    "content": prompt,
                }
            ],
            max_tokens=230
        )
        # Update text based on successful response
        text = text_response.choices[0].message.content.strip()
        combined_text = f"{visual_text} {text}"

    except Exception as e:
        logging.error(f"An error occurred in generate_artwork_info: {e}")

    # Logging after ensuring variables are initialized and potentially updated
    logging.info(f"Visual Description from GPT-4: {visual_text}")
    logging.info(f"Textual Interpretation from GPT-3.5: {text}")
    logging.info(f"Combined Artwork Info: {combined_text}")

    return combined_text.strip()



@app.route('/')
def landing_page():
    return render_template('landing.html')

@app.route('/app')
def painting_of_the_day():
    painting = scrape_painting()
    if not painting:
        painting_info = "Information could not be generated due to an error."
    else:
        painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["dated"], painting["image_url"])
        logging.info(f"Rendering image URL to template: {painting['image_url']}")

    painting["info"] = painting_info if painting_info else "Information could not be generated."
    return render_template('index.html', painting=painting, hide_loader=True)

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/refresh', methods=['GET'])
def refresh():
    painting = scrape_painting()
    if not painting:
        return jsonify({"error": "No painting available"})
    painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["dated"], painting["image_url"])
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
        # No

@app.route('/favorites')
def favorites():
    return render_template('favorites.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)