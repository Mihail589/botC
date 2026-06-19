import telebot, random as rd, json as js, config as cfg, os, requests, threading as th, time
from telebot import types
try:
	with open("mess.json", "r") as f:
		messages = js.load(f)
          
except:
	messages = []
	with open("mess.json", "w") as f:
		js.dump(messages, f)

bot = telebot.TeleBot(cfg.TOKEN)

@bot.message_handler(commands=["today"])
def echo_all(message):
	data = rd.choice(messages)
	if data["image"] == None:
		bot.send_message(message.from_user.id, data["text"])
	else:
		with open("temp.jpg", "wb") as f:
			f.write(bytes.fromhex(data["image"]))

		with open("temp.jpg", "rb") as photo:
			bot.send_photo(message.chat.id,photo)
			bot.send_message(message.chat.id,data["text"])
			os.remove("temp.jpg")

@bot.message_handler(commands=["admin"], func=lambda m: m.from_user.id in cfg.ADMINS)
def admin(message):
	keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
	btn1 = types.KeyboardButton('Добавить')
	btn2 = types.KeyboardButton('Отмена')
	keyboard.row(btn1, btn2)
	bot.send_message(message.from_user.id, "Привет выбери уже существующий элемент или добавь новый", reply_markup=keyboard)
	str = "Доступные варианты:\n"
	for i in range(len(messages)):
		if len(messages[i]["text"]) <= 10:
			str += f"{i + 1}. {messages[i]["text"]}\n"
		else:
			str += f"{i + 1}. {messages[i]["text"][:10]}\n"
	bot.send_message(message.from_user.id, str, reply_markup=keyboard)
	bot.register_next_step_handler(message, actions)

idc = 0

def actions(message):
	global idc
	data = message.text
	
	keyboard = types.ReplyKeyboardRemove()
	if data == "Добавить":
		bot.send_message(message.from_user.id, "Хорошо напиши текст карты", reply_markup=keyboard)
		bot.register_next_step_handler(message, add)
	elif data == "Отмена":
		bot.send_message(message.from_user.id, "Отмена", reply_markup=keyboard)
	else:
		bot.send_message(message.from_user.id, "Хорошо\nВот карта\nЧто делать далее", reply_markup=keyboard)
		keyboard = types.InlineKeyboardMarkup(row_width=2)
		btn1 = types.InlineKeyboardButton('Удалить', callback_data='yes')
		keyboard.add(btn1)
		idc = int(data) - 1
		if messages[int(data) - 1]['image'] == None:
			print("OK")
			bot.send_message(message.chat.id, messages[int(data) - 1]["text"], reply_markup=keyboard)
		else:
			with open("temp.jpg", "wb") as f:
				f.write(bytes.fromhex(messages[int(data) - 1]["image"]))

			with open("temp.jpg", "rb") as photo:
				bot.send_photo(message.chat.id,photo)
				bot.send_message(message.chat.id, messages[int(data) - 1]["text"], reply_markup=keyboard)
				os.remove("temp.jpg")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
	global messages
	if call.data == 'yes':
		bot.answer_callback_query(call.id, "Карта удалена")
		messages.remove(messages[idc])
		with open("mess.json", "w") as f:
			js.dump(messages, f)

def add(message):
	global messages
	post = message.text
	messages.append({"text": post, "image": None})
	bot.send_message(message.from_user.id, "Хорошо теперь скинь изображение если не надо отправь что угодно")
	bot.register_next_step_handler(message, photo)

def photo(message):
	global messages
	print(message.content_type)
	if message.content_type == "image" or message.content_type == "photo":
		file_id = message.photo[-1].file_id
		file_info = bot.get_file(file_id)
		downloaded_file = bot.download_file(file_info.file_path)
		messages[-1]["image"] = downloaded_file.hex()
		print("OK")
	bot.send_message(message.from_user.id, "Карта сохранена")
	with open("mess.json", "w") as f:
		js.dump(messages, f)
print("gu")
bot.polling()
	
