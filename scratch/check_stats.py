import sys
import os
sys.path.append(os.getcwd())

from PIL import Image
from blank_page_detector import get_page_stats

img = Image.open('scratch/test_page.jpg')
stats = get_page_stats(img)
print(stats)
