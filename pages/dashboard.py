import streamlit as st
from pyzbar.pyzbar import decode
from PIL import Image

import numpy as np

cam = st.camera_input("Scan barcode")

if cam is not None:
    img = Image.open(cam)
    
    decoded = decode(img)
    st.write(decoded)
    decoded[0]