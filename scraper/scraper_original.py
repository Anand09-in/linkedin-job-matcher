import logging
import csv
import os
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, \
    OnSiteOrRemoteFilters, SalaryBaseFilters
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from linkedin_jobs_scraper.strategies import AuthenticatedStrategy

# Change root logger level (default is WARN)
logging.basicConfig(level=logging.INFO)
#os.setenv('LI_AT_COOKIE', 'AQEDATK9wlsBXy5wAAABnPiKaj4AAAGdHJbuPk4AjX-fW6yPPiFxBEsYMjDm3WkqUJh6KxIJDD46GLasCgrnET8zV9JQGmuExXaNSkd_Btf-bkhyLJPB3TCWxTqH178l7gDWYIXrcl-wOAOx1ht5WpmZ')  # Disable webdriver_manager logs

# Fired once for each successfully processed job
def on_data(data: EventData):
    print(data.title, data.company, data.link)

    with open("mle_jobs.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            data.title,
            data.company,
            data.location,
            data.date,
            data.link
        ])


# Fired once for each page (25 jobs)
def on_metrics(metrics: EventMetrics):
    print('[ON_METRICS]', str(metrics))


def on_error(error):
    print('[ON_ERROR]', error)


def on_end():
    print('[ON_END]')


scraper = LinkedinScraper(
    
    chrome_executable_path=ChromeDriverManager().install(), # Custom Chrome executable path (e.g. /foo/bar/bin/chromedriver)
    chrome_binary_location=None,  # Custom path to Chrome/Chromium binary (e.g. /foo/bar/chrome-mac/Chromium.app/Contents/MacOS/Chromium)
    chrome_options=None,  # Custom Chrome options here
    headless=True,  # Overrides headless mode only if chrome_options is None
    max_workers=1,  # How many threads will be spawned to run queries concurrently (one Chrome driver for each thread)
    slow_mo=1.5,  # Slow down the scraper to avoid 'Too many requests 429' errors (in seconds)
    page_load_timeout=40  # Page load timeout (in seconds)    
)

# Add event listeners
scraper.on(Events.DATA, on_data)
scraper.on(Events.ERROR, on_error)
scraper.on(Events.END, on_end)
scraper.on(Events.METRICS, on_metrics)

queries = [
    Query(
        query='Machine Learning Engineer with less than 2 years of experience',
        options=QueryOptions(
            locations=['Bangalore, India', 'Mumbai, India', 'Pune, India'],  # Filter by locations.
            apply_link=True,  # Try to extract apply link (easy applies are skipped). If set to True, scraping is slower because an additional page must be navigated. Default to False.
            skip_promoted_jobs=True,  # Skip promoted jobs. Default to False.
            #page_offset=2,  # How many pages to skip
            limit=50,
            filters=QueryFilters(
                relevance=RelevanceFilters.RECENT,
                time=TimeFilters.MONTH,
                type=[TypeFilters.FULL_TIME],
                # on_site_or_remote=[OnSiteOrRemoteFilters.REMOTE],
                #experience=[ExperienceLevelFilters.ENTRY_LEVEL, ExperienceLevelFilters.ASSOCIATE],
                #base_salary=SalaryBaseFilters.SALARY_100K
            )
        )
    )
]

scraper.run(queries)