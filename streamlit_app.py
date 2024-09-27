import re
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from bs4 import BeautifulSoup
from loguru import logger
from requests import HTTPError

MAX_PAGES = 50
DELAY = 1  # Delay between requests in seconds

def __response_hook(r, *args, **kwargs):
    try:
        r.raise_for_status()
    except HTTPError as e:
        error_msg = BeautifulSoup(r.text, "html.parser").text.strip()
        if "captcha" in error_msg.lower():
            return "Amazon ha rilevato un'attività insolita. Prova più tardi."
        elif e.response.status_code == 403:
            return "Accesso negato. Amazon potrebbe star bloccando le nostre richieste."
        elif e.response.status_code == 404:
            return "Pagina non trovata. Il prodotto potrebbe non esistere."
        else:
            return f"Si è verificato un errore: {error_msg}"
    return r

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/111.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3",
    }
)
session.hooks = {"response": __response_hook}

def get(url, **kwargs):
    time.sleep(DELAY)  # Add delay between requests
    response = session.get(url, **kwargs)
    if isinstance(response, str):  # Error occurred
        st.error(response)
        return None
    return response

@st.cache_data
def search(q: str):
    site = "amazon.it"
    url = f"https://{site}/s?k={q}"

    response = get(url)
    if response is None:
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    pages_element = soup.find_all("span", "s-pagination-item")
    pages = int(pages_element[-1].text) if pages_element else 1

    if pages > MAX_PAGES:
        pages = MAX_PAGES

    def get_results(page: int):
        response = get(url, params={"page": page})
        if response is None:
            return []

        soup = BeautifulSoup(response.content, "html.parser")
        divs = soup.find_all("div", attrs={"data-component-type": "s-search-result"})

        if not divs:
            logger.error(f"Nessun risultato trovato nella pagina HTML: {soup}")
            return []

        results = []
        for div in divs:
            try:
                result = {}
                asin = div["data-asin"]
                result["asin"] = asin
                result["img"] = div.find("img", "s-image")["src"]
                result["description"] = ": ".join(
                    h2.text.strip() for h2 in div.find_all("h2")
                )
                result["link"] = f"https://{site}/dp/{asin}"
                price = div.find("span", "a-price")
                if price:
                    result["price"] = price.find("span", "a-offscreen").text

                rating = div.find(
                    "span",
                    attrs={
                        "aria-label": lambda l: l
                        and re.fullmatch(".* su .* stelle", l)
                    },
                )
                if rating:
                    result["rating"] = float(rating["aria-label"].split(" ")[0].replace(",", "."))
                number_of_reviews = div.find(
                    "a", href=lambda h: h and h.endswith("#customerReviews")
                )
                if number_of_reviews:
                    result["number_of_reviews"] = int(
                        number_of_reviews.text.strip()
                        .replace(".", "")
                        .replace("(", "")
                        .replace(")", "")
                    )

                results.append(result)
            except Exception as e:
                logger.error(f"Errore nel processare il div: {div}. Errore: {e}")

        return results

    with ThreadPoolExecutor() as t:
        return [item for sublist in t.map(get_results, range(1, pages + 1)) for item in sublist]

def main():
    st.title("ASearch")
    st.subheader("Una ricerca migliore su Amazon")

    st.warning(
        "Questa app effettua scraping su Amazon per scopi educativi. "
        "Potrebbe non funzionare in modo costante a causa delle misure anti-scraping di Amazon."
    )

    term = st.text_input("Cerca")

    user_agent = st.text_input(
        "Inserisci una stringa User-Agent (opzionale)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    )
    if user_agent:
        session.headers.update({"User-Agent": user_agent})

    if term:
        with st.spinner("Ricerca in corso..."):
            df = pd.DataFrame(search(term))

        if df.empty:
            st.error("Nessun risultato trovato o si è verificato un errore durante il recupero dei dati.")
        else:
            df["price_value"] = df.price.str.replace("€", "").str.replace(".", "").str.replace(",", ".").astype(float)

            price_range = st.slider(
                "Prezzo",
                df.price_value.min(),
                df.price_value.max(),
                (df.price_value.min(), df.price_value.max()),
                format="€%.2f",
            )

            df_filtered = df[df.price_value.between(*price_range)]

            st.dataframe(
                df_filtered[
                    ["link", "img", "description", "price_value", "number_of_reviews", "rating"]
                ],
                column_config={
                    "link": st.column_config.LinkColumn("Link", display_text="Apri"),
                    "img": st.column_config.ImageColumn("Immagine"),
                    "description": "Descrizione",
                    "price_value": st.column_config.NumberColumn("Prezzo", format="€%.2f"),
                    "number_of_reviews": "Recensioni",
                    "rating": st.column_config.NumberColumn("Valutazione", format="%.1f ⭐️"),
                },
                use_container_width=True,
            )

            st.plotly_chart(px.histogram(df_filtered.price_value, title="Distribuzione dei Prezzi"))

if __name__ == "__main__":
    main()
