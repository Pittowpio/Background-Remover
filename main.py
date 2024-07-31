import os
import time
import hashlib
import telebot
from PIL import Image, ImageDraw
from rembg import remove
from telebot import types
from pymongo import MongoClient

TOKEN = "Your Bot token"
MONGO_URI = "Your mongo uri"
IMAGES_DIR = 'images'
PRIVATE_CHANNEL_ID = -1002235773657  # Replace with your actual private channel ID

bot = telebot.TeleBot(TOKEN)

client = MongoClient(MONGO_URI)
db = client['bot_database']
users_collection = db['users']
file_mapping_collection = db['file_mapping']

def add_user(user_id, user_name):
    if not users_collection.find_one({"user_id": user_id}):
        users_collection.insert_one({"user_id": user_id, "user_name": user_name})

def get_total_users():
    return users_collection.count_documents({})

def can_send_image(user_id):
    user = users_collection.find_one({"user_id": user_id})
    if user and 'last_image_time' in user:
        last_time = user['last_image_time']
        current_time = time.time()
        if current_time - last_time < 60:
            return False
    return True

def update_last_image_time(user_id):
    current_time = time.time()
    users_collection.update_one({"user_id": user_id}, {"$set": {"last_image_time": current_time}})

def generate_short_id(file_id):
    return hashlib.md5(file_id.encode()).hexdigest()[:10]

def change_background_color(image, color):
    colors = {
        'grey': (169, 169, 169),
        'black': (0, 0, 0),
        'white': (255, 255, 255),
        'blue': (0, 0, 255),
        'red': (255, 0, 0),
        'orange': (255, 165, 0),
        'brown': (139, 69, 19),
        'yellow': (255, 255, 0),
        'green': (0, 128, 0),
        'pink': (255, 192, 203),
        'purple': (128, 0, 128),
        'cyan': (0, 255, 255),
        'magenta': (255, 0, 255),
        'lime': (50, 205, 50)
    }
    color = colors.get(color, (255, 255, 255))  # Default to white if color not found

    image = image.convert("RGBA")
    background = Image.new("RGBA", image.size, color)
    combined = Image.alpha_composite(background, image)
    return combined

def create_checkboard_pattern(image_size, tile_size=10):
    width, height = image_size
    pattern = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(pattern)

    for y in range(0, height, tile_size):
        for x in range(0, width, tile_size):
            color = (255, 255, 255, 255) if (x // tile_size) % 2 == (y // tile_size) % 2 else (169, 169, 169, 255)
            draw.rectangle([x, y, x + tile_size, y + tile_size], fill=color)

    return pattern

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    add_user(user_id, user_name)
    
    bot.send_message(
        message.chat.id,
        f"Hello dear {user_name} \n\n"
        "- You can easily remove the background from images using this bot.\n\n"
        "- You can also Change background color !\n\n"
        "Just send me the image "
    )

@bot.message_handler(commands=['stats'])
def send_stats(message):
    total_users = get_total_users()
    bot.send_message(message.chat.id, f'Total users: {total_users}')

@bot.message_handler(content_types=['photo'])
def handle_image(message):
    user_id = message.from_user.id

    if not is_user_in_channel(user_id):
        markup = types.InlineKeyboardMarkup()
        join_button = types.InlineKeyboardButton("Join Channel", url="https://t.me/+XsHpoz7cEP5hMzE1")
        markup.add(join_button)
        bot.send_message(
            message.chat.id, 
            'Please join the channel to use this bot ',
            reply_markup=markup
        )
        return

    if not can_send_image(user_id):
        bot.send_message(message.chat.id, 'You can only send one image per minute. Please wait a bit and try again.')
        return

    bot.send_message(message.chat.id, 'Processing Your Image ')

    file_id = message.photo[-1].file_id
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    if not os.path.exists(IMAGES_DIR):
        os.makedirs(IMAGES_DIR)

    file_name = f"{IMAGES_DIR}/{file_id}.png"
    
    with open(file_name, 'wb') as new_file:
        new_file.write(downloaded_file)

    input_image = Image.open(file_name)
    output_image = remove(input_image)
    
    output_dir = f'{IMAGES_DIR}/removed'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    output_path = f'{output_dir}/{file_id}.png'
    output_image.save(output_path)

    short_id = generate_short_id(file_id)

    file_mapping_collection.insert_one({"short_id": short_id, "file_path": output_path})

    markup = types.InlineKeyboardMarkup()
    colors = ['grey', 'black', 'white', 'blue', 'red', 'orange', 'brown', 'yellow', 'green', 'pink', 'purple', 'cyan', 'magenta', 'lime']
    for i in range(0, len(colors), 3):
        row_buttons = [types.InlineKeyboardButton(color.capitalize(), callback_data=f"color_{short_id}_{color}") for color in colors[i:i+3]]
        markup.row(*row_buttons)
    
    professional_button = types.InlineKeyboardButton("Professional Colour", callback_data=f"pro_{short_id}")
    markup.row(professional_button)

    caption = "The Background is removed. You can also change it from below "

    with open(output_path, 'rb') as img:
        bot.send_photo(message.chat.id, img, caption=caption, reply_markup=markup)
    
    update_last_image_time(user_id)

    time.sleep(1)


@bot.callback_query_handler(func=lambda call: call.data.startswith('color_'))
def apply_color(call):
    data = call.data.split('_')
    short_id = data[1]
    color = data[2]

    mapping = file_mapping_collection.find_one({"short_id": short_id})
    if not mapping:
        bot.send_message(call.message.chat.id, "Error: File not found.")
        return

    output_path = mapping['file_path']
    color_path = f'{IMAGES_DIR}/removed/{short_id}_{color}.png'

    input_image = Image.open(output_path)
    colored_image = change_background_color(input_image, color)
    colored_image.save(color_path)

    markup = types.InlineKeyboardMarkup()
    colors = ['grey', 'black', 'white', 'blue', 'red', 'orange', 'brown', 'yellow', 'green', 'pink', 'purple', 'cyan', 'magenta', 'lime']
    for i in range(0, len(colors), 3):
        row_buttons = [types.InlineKeyboardButton(color.capitalize(), callback_data=f"color_{short_id}_{color}") for color in colors[i:i+3]]
        markup.row(*row_buttons)
    
    professional_button = types.InlineKeyboardButton("Professional Colour", callback_data=f"pro_{short_id}")
    markup.row(professional_button)

    caption = "The Background is removed. You can also change it from below "

    with open(color_path, 'rb') as img:
        bot.edit_message_media(media=types.InputMediaPhoto(img), chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

    bot.edit_message_text(caption, chat_id=call.message.chat.id, message_id=call.message.message_id)

    time.sleep(1)
    os.remove(color_path)

def create_grey_white_checkboard_pattern(image_size, tile_size=10):
    width, height = image_size
    pattern = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(pattern)

    for y in range(0, height, tile_size):
        for x in range(0, width, tile_size):
            color = (255, 255, 255, 255) if (x // tile_size) % 2 == (y // tile_size) % 2 else (169, 169, 169, 255)
            draw.rectangle([x, y, x + tile_size, y + tile_size], fill=color)

    return pattern

@bot.callback_query_handler(func=lambda call: call.data.startswith('pro_'))
def apply_professional_color(call):
    short_id = call.data.split('_')[-1]

    mapping = file_mapping_collection.find_one({"short_id": short_id})
    if not mapping:
        bot.send_message(call.message.chat.id, "Error: File not found.")
        return

    output_path = mapping['file_path']
    pro_path = f'{IMAGES_DIR}/removed/{short_id}_pro.png'

    input_image = Image.open(output_path)
    checkboard_pattern = create_grey_white_checkboard_pattern(input_image.size)
    pro_image = Image.alpha_composite(checkboard_pattern, input_image)
    pro_image.save(pro_path)

    markup = types.InlineKeyboardMarkup()
    colors = ['grey', 'black', 'white', 'blue', 'red', 'orange', 'brown', 'yellow', 'green', 'pink', 'purple', 'cyan', 'magenta', 'lime']
    for i in range(0, len(colors), 3):
        row_buttons = [types.InlineKeyboardButton(color.capitalize(), callback_data=f"color_{short_id}_{color}") for color in colors[i:i+3]]
        markup.row(*row_buttons)
    
    professional_button = types.InlineKeyboardButton("Professional Colour", callback_data=f"pro_{short_id}")
    markup.row(professional_button)

    caption = "The Background is removed. You can also change it from below "

    with open(pro_path, 'rb') as img:
        bot.edit_message_media(media=types.InputMediaPhoto(img), chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

    bot.edit_message_text(caption, chat_id=call.message.chat.id, message_id=call.message.message_id)

    time.sleep(1)
    os.remove(pro_path)

def is_user_in_channel(user_id):
    try:
        member = bot.get_chat_member(PRIVATE_CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

@bot.message_handler(func=lambda message: True)
def handle_other(message):
    if message.content_type != 'photo' and message.text != '/start' and message.text != '/stats':
        return

bot.polling(none_stop=True)
