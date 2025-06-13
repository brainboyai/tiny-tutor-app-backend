import random

# The base URL for your raw GitHub content.
# This points to the 'main' branch of your game-objects repository.
ASSET_BASE_URL = "https://raw.githubusercontent.com/brainboyai/tiny-tutor-game-objects/main/"

def get_image_urls(object_names: list[str]) -> dict[str, str]:
    """
    Constructs full image URLs for a list of object names.

    Args:
        object_names: A list of object names (e.g., ['tiger', 'rice', 'wolf']).

    Returns:
        A dictionary mapping each object name to its corresponding image URL.
        It randomly selects between 'object.png' and 'object (1).png'.
    """
    image_urls = {}
    for name in object_names:
        if not name or not isinstance(name, str):
            continue
        
        # Clean and format the name for the URL
        url_friendly_name = name.lower().strip()

        # Randomly choose between the base name and a variant, like "cow.png" or "cow (1).png"
        # This adds variety if you have multiple images for one object.
        if random.choice([True, False]):
            # Append a variant number, handling spaces for the URL
            image_filename = f"{url_friendly_name}%20(1).png"
        else:
            image_filename = f"{url_friendly_name}.png"
            
        full_url = f"{ASSET_BASE_URL}{image_filename}"
        image_urls[name] = full_url
        
    return image_urls