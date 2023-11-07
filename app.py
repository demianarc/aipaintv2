from flask import Flask, render_template
from flask import jsonify
import requests
from bs4 import BeautifulSoup
import openai
import random
import os
import json



app = Flask(__name__)

# Load OpenAI API key from environment variables
openai.api_key = os.environ.get("OPENAI_API_KEY")
API_ENDPOINT = "https://api.openai.com/v1/chat/completions"

def scrape_painting():
    api_key = os.environ.get("HARVARD_API_KEY")
    url = f"https://api.harvardartmuseums.org/object?apikey={api_key}&size=100&sort=random&classification=Paintings&hasimage=1&sortorder=asc"
    response = requests.get(url)
    print(f"URL: {url}")
    print(f"Response status code: {response.status_code}")
    print(f"Response text: {response.text}")
    data = response.json()

    if "records" not in data or not data["records"]:
        return {
            "image_url": None,
            "title": None,
            "artist": None,
            "date": None
        }

    painting = random.choice(data["records"])

    image_url = painting["primaryimageurl"]
    title = painting["title"]
    artist = painting["people"][0]["name"] if "people" in painting and painting["people"] else "Unknown artist"
    date = painting["dated"]

    return {
        "image_url": image_url,
        "title": title,
        "artist": artist,
        "date": date
    }

def generate_artwork_info(artist, title, image_url):
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # First, get the visual interpretation using the image to ensure factual accuracy.
    try:
        visual_response = openai.ChatCompletion.create(
            model="gpt-4-vision-preview",  # Use the vision model here
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this painting, focusing on its most notable visual aspects."},
                        {"type": "image_url", "image_url": image_url},
                    ]
                }
            ],
            max_tokens=150  # Increased tokens to get more detail
        )

        visual_text = visual_response.choices[0].message["content"]

        # Now, use the visual details to inform the chat model's emotional interpretation.
        prompts = [
            f"The painting '{title}' by {artist} features {visual_text}. What historical narratives or emotions might these details suggest?",
            # Additional prompts can be crafted similarly, using visual_text.
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

        # Combine both responses with titles for clarity.
        combined_text = f"VISUAL_MARKER{visual_text}HISTORICAL_MARKER{text}"


        return combined_text.strip()
    except openai.error.OpenAIError as e:
        print(f"An error occurred: {e}")
        return "An error occurred while processing the image. Please try again later."
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return "An unexpected error occurred. Please try again later."


@app.route('/')
def painting_of_the_day():
    painting = scrape_painting()
    # Make sure to pass all three parameters artist, title, and image_url
    painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["image_url"])
    painting["info"] = painting_info if painting_info else "Information could not be generated."
    painting_json = json.dumps(painting)
    return render_template('index.html', painting=painting, painting_json=painting_json)

@app.route('/refresh')
def refresh():
    painting = scrape_painting()
    painting_info = generate_artwork_info(painting["artist"], painting["title"], painting["image_url"])
    painting["info"] = painting_info
    return jsonify(painting)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
