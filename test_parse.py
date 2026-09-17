import re

# Sample snippet resembling comfy.ua meta tag as it appears in raw HTML
comfy_html_sample = '''
<meta property="og:type" content="product" />
<meta property="product:price:amount" content="17999" />
<meta property="product:price:currency" content="UAH" />
'''

from bs4 import BeautifulSoup
soup = BeautifulSoup(comfy_html_sample, "html.parser")
tag = soup.find("meta", attrs={"property": "product:price:amount"})
print("Comfy price parsed:", tag["content"] if tag else None)

# Sample text resembling auto.ria visible text for listings (from the fetched page)
auto_ria_text_sample = """
Chevrolet Bolt EV 2023I покоління (FL) • 65 kWh (200 к.с.) • Base17 950 $ · 804 160 грн 142 тис. км
Chevrolet Bolt EV 2016І покоління13 999 $ 13 500 $ · 604 800 грн 132 тис. км
Chevrolet Bolt EV 2017І покоління • 66 kWh (200 к.с.) • Base14 999 $ 14 500 $ · 649 600 грн 72 тис. км
"""

prices = []
for m in re.finditer(r'(\d[\d\s]{2,9}\d)\s?\$\s*·', auto_ria_text_sample):
    num = m.group(1).replace(" ", "").replace("\xa0", "")
    prices.append(float(num))

print("Auto.ria prices found:", prices)
print("Min price:", min(prices) if prices else None)
