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
import os
import json

def find_matching_recall(recalls, upc_code):
  """
  Finds the recall object that matches the given UPC code.

  Args:
    recalls: A list of recall objects.
    upc_code: The UPC code to search for.

  Returns:
    The recall object that matches the UPC code, or None if no match is found.
  """
  value = []
  for recall in recalls:
    for product_upc in recall['ProductUPCs']:
        if product_upc['UPC'] == upc_code:
           value.append(recall)


  return value

file_path = "output.json"
with open(file_path, 'r') as f:
    recalls = json.load(f)

field_name = 'UPC'
upc_debug = '708953651019'

print(find_matching_recall(recalls, upc_debug))


# "https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallTitle=Food&ProductUPCs=UPC"

# print(requests.get("https://www.saferproducts.gov/RestWebServices/Recall?format=json", allow_redirects=False))
# os.system("curl https://www.saferproducts.gov/RestWebServices/Recall?format=json > output.json")