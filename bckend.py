CARRIERS = {
    "att": "@mms.att.net",
    "tmobile": "@tmomail.net",
    "verizon": "@vzwpix.com",
    "sprint": "@messaging.sprintpcs.com"
}
EMAIL = ''
PASSWORD = ""
def send_message(phone_number, carrier, message):
    recipient = phone_number + CARRIERS[carrier]
    auth = (EMAIL, PASSWORD)

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(auth[0], auth[1])

    server.sendmail(auth[0], recipient, message)
    print(f"Usage: python3 {phone_number, carrier, message}")

import requests

"https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallTitle=Food&ProductUPCs=UPC"
