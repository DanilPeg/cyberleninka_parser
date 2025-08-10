    import os
    import time
    import random
    import argparse
    import requests
    from urllib.parse import urljoin, urlparse
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    MAX_FILENAME_LENGTH = 100

    def sanitize_filename(name: str) -> str:
        """Удаляет запрещённые символы, обрезает длину и убирает лишние пробелы."""
        name = name.replace('\n', ' ').strip()
        prohibited = "\\/:*?\"<>|"
        sanitized = ''.join(c for c in name if c not in prohibited)
        sanitized = ' '.join(sanitized.split())
        if len(sanitized) > MAX_FILENAME_LENGTH:
            sanitized = sanitized[:MAX_FILENAME_LENGTH].rstrip() + '...'
        return sanitized

    def download_pdf_sync(pdf_url, filepath, timeout=30):
        """Синхронно скачивает PDF файл"""
        try:
            response = requests.get(pdf_url, timeout=timeout)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                return True, filepath
            else:
                return False, f"HTTP {response.status_code}"
        except Exception as e:
            return False, str(e)

    def check_article_has_abstract(page, article_element):
        """Проверяет наличие аннотации у статьи"""
        try:
            # Ищем аннотацию в статье
            abstract_element = article_element.locator('p').first
            if abstract_element.count() > 0:
                abstract_text = abstract_element.inner_text().strip()
                return len(abstract_text) > 0
            return False
        except Exception:
            return False

    def process_article_page(page, article_url, timeout=20000):
        """Обрабатывает страницу статьи и извлекает ссылку на PDF"""
        try:
            page.goto(article_url, wait_until='domcontentloaded')
            
            # Ищем ссылку на PDF
            pdf_href = page.locator('a#btn-download').get_attribute('href')
            return pdf_href
        except Exception as e:
            print(f"Ошибка при обработке {article_url}: {e}")
            return None

    def setup_browser_stealth(browser):
        """Настраивает браузер для обхода детекции ботов"""
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ru-RU',
            timezone_id='Europe/Moscow',
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        )
        
        # Добавляем случайные задержки
        page = context.new_page()
        page.set_default_navigation_timeout(30000)
        
        # Эмулируем человеческое поведение
        page.add_init_script("""
            // Скрываем признаки автоматизации
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // Эмулируем случайные движения мыши
            const originalQuerySelector = document.querySelector;
            document.querySelector = function(...args) {
                const result = originalQuerySelector.apply(this, args);
                if (result && Math.random() < 0.1) {
                    // Случайная задержка
                    return new Promise(resolve => setTimeout(() => resolve(result), Math.random() * 100));
                }
                return result;
            };
        """)
        
        return context, page

    # вспомогательная функция, использовалась для поиска капчи, можно заккоментить
    def check_captcha(page):
        """Проверяет наличие капчи на странице"""
        try:
            
            captcha_selectors = [
                'form[action*="captcha"]',
                'input[name*="captcha"]',
                '.captcha',
                '#captcha',
                'iframe[src*="captcha"]',
                'div[class*="captcha"]',
                'img[src*="captcha"]'
            ]
            
            for selector in captcha_selectors:
                if page.locator(selector).count() > 0:
                    print(f"[ОТЛАДКА] Найден элемент капчи: {selector}")
                    return True
            
            page_text = page.content().lower()
            
            captcha_keywords = [
                'captcha', 'капча', 'robot', 'бот', 'verification', 'проверка', 'security'
            ]
            
            for keyword in captcha_keywords:
                if keyword in page_text:
                    if any(context in page_text for context in ['captcha', 'капча', 'robot', 'verification']):
                        print(f"[ОТЛАДКА] Найдено ключевое слово капчи: {keyword}")
                        return True
                    
            return False
        except Exception as e:
            print(f"[ОТЛАДКА] Ошибка при проверке капчи: {e}")
            return False

    def process_and_download_articles_from_page(page, category_url, page_num, target_dir, timeout=20000, min_delay=0.2, max_delay=0.8):
        """Обрабатывает страницу категории и сразу скачивает найденные статьи"""
        try:
            print(f"[ОТЛАДКА] Загружаем страницу {page_num}...")
            
            if page_num == 1:
                page.goto(category_url, wait_until='domcontentloaded')
            else:
                page.goto(f"{category_url}?page={page_num}", wait_until='domcontentloaded')
            
            print(f"[ОТЛАДКА] Страница {page_num} загружена")
            
            time.sleep(random.uniform(1, 3))
            
            # ВРЕМЕННО ОТКЛЮЧАЕМ ПРОВЕРКУ КАПЧИ
            # print(f"[ОТЛАДКА] Проверяем капчу на странице {page_num}...")
            # if check_captcha(page):
            #     print(f"[ВНИМАНИЕ] Обнаружена капча на странице {page_num}! Остановка парсинга.")
            #     return False, 0
            
            print(f"[ОТЛАДКА] Ищем статьи...")
            
            articles = []
            article_elements = page.locator('a:has(div.title)')
            article_count = article_elements.count()
            
            print(f"[ОТЛАДКА] Найдено {article_count} элементов статей")
            
            for idx in range(article_count):
                article_element = article_elements.nth(idx)
                
                if check_article_has_abstract(page, article_element):
                    href = article_element.get_attribute('href') or ''
                    article_url = urljoin(category_url, href)
                    
                    title_raw = article_element.locator('div.title').inner_text().strip()
                    title = sanitize_filename(title_raw)
                    
                    articles.append({
                        'url': article_url,
                        'title': title
                    })
            
            print(f"Страница {page_num}: найдено {len(articles)} статей с аннотациями")
            
            downloaded_count = 0
            for i, article in enumerate(articles):
                filename = f"{article['title']}.pdf"
                filepath = os.path.join(target_dir, filename)
                
                if os.path.exists(filepath):
                    print(f"  Пропустить (уже скачано): {article['title']}")
                    continue
                
                try:
                    print(f"[ОТЛАДКА] Обрабатываем статью {i+1}/{len(articles)}: {article['title']}")
                    
                    pdf_href = process_article_page(page, article['url'], timeout)
                    if pdf_href:
                        pdf_url = urljoin(article['url'], pdf_href)
                        
                        success, message = download_pdf_sync(pdf_url, filepath)
                        if success:
                            downloaded_count += 1
                            print(f"  [OK] Скачано ({downloaded_count}): {article['title']}")
                        else:
                            print(f"  [ОШИБКА] Ошибка скачивания {article['title']}: {message}")
                    else:
                        print(f"  [ОШИБКА] PDF не найден: {article['title']}")
                    
                    if i < len(articles) - 1:
                        time.sleep(random.uniform(min_delay, max_delay))
                        
                except Exception as e:
                    print(f"  [ОШИБКА] Ошибка при обработке {article['title']}: {e}")
            
            return True, downloaded_count
            
        except Exception as e:
            print(f"Ошибка при обработке страницы {page_num}: {e}")
            return True, 0

    def main():
        parser = argparse.ArgumentParser(
            description="Быстрый парсер статей CyberLeninka с фильтрацией по аннотациям"
        )
        parser.add_argument('--category-url', '-u', required=True,
                            help='URL рубрики на CyberLeninka')
        parser.add_argument('--max-pages', '-n', type=int, default=10,
                            help='Максимальное число страниц категории для обхода')
        parser.add_argument('--start-page', type=int, default=1,
                            help='Номер страницы, с которой начать скачивание (по умолчанию 1)')
        parser.add_argument('--end-page', type=int, default=None,
                            help='Номер страницы, на которой закончить скачивание (по умолчанию max-pages)')
        parser.add_argument('--min-delay', type=float, default=0.5,
                            help='Минимальная задержка между запросами (сек)')
        parser.add_argument('--max-delay', type=float, default=1.5,
                            help='Максимальная задержка между запросами (сек)')
        parser.add_argument('--timeout', type=int, default=20000,
                            help='Таймаут навигации Playwright (мс)')
        parser.add_argument('--stealth', action='store_true',
                            help='Включить режим стелс для обхода антибот-защиты')
        parser.add_argument('--debug', action='store_true',
                            help='Включить отладочный режим')
        args = parser.parse_args()

        start_page = args.start_page
        end_page = args.end_page if args.end_page is not None else args.max_pages
        
        if start_page < 1:
            print("Ошибка: start-page не может быть меньше 1")
            return
        
        if end_page < start_page:
            print("Ошибка: end-page не может быть меньше start-page")
            return

        with sync_playwright() as p:
            if args.stealth:
                browser = p.chromium.launch(headless=False)  
                context, page = setup_browser_stealth(browser)
            else:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_default_navigation_timeout(args.timeout)
            
            print("[ОТЛАДКА] Загружаем главную страницу категории...")
            page.goto(args.category_url)
            try:
                raw_category = page.locator('h1').inner_text()
                category_name = sanitize_filename(raw_category.splitlines()[0])
            except Exception:
                category_name = sanitize_filename(os.path.basename(urlparse(args.category_url).path))

            root_dir = os.path.join(os.getcwd(), 'pages')
            target_dir = os.path.join(root_dir, category_name)
            os.makedirs(target_dir, exist_ok=True)

            print(f"Категория: {category_name}")
            print(f"Обрабатываем страницы {start_page}-{end_page}...")

            total_downloaded = 0
            for page_num in range(start_page, end_page + 1):
                try:
                    success, downloaded = process_and_download_articles_from_page(
                        page, args.category_url, page_num, target_dir, 
                        args.timeout, args.min_delay, args.max_delay
                    )
                    
                    # ВРЕМЕННО ОТКЛЮЧАЕМ ПРОВЕРКУ КАПЧИ
                    # if not success:
                    #     print(f"[ОСТАНОВКА] Остановка парсинга из-за капчи на странице {page_num}")
                    #     break
                    
                    total_downloaded += downloaded
                    
                    # Увеличенная задержка между страницами для обхода защиты
                    if page_num < end_page:
                        delay = random.uniform(args.min_delay * 2, args.max_delay * 2)
                        print(f"Пауза {delay:.1f} сек перед следующей страницей...")
                        time.sleep(delay)
                        
                except Exception as e:
                    print(f"Ошибка при обработке страницы {page_num}: {e}")
                    continue

            if args.stealth:
                context.close()
            browser.close()
            print(f"Готово! Всего скачано PDF: {total_downloaded}")

    if __name__ == '__main__':
        main() 