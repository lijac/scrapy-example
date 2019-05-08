import scrapy
from isbn.items import AbeBook_Item
import re
from datetime import datetime
from .base_spider import BaseSpider  
import logging

class AbeSpider(BaseSpider):
    name = "abe"
    log_name = name

    utc_now = datetime.utcnow()

    custom_settings = {
        'FEED_URI': name + utc_now.strftime('_%Y%m%d.csv'),
        'FEED_FORMAT': 'csv'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def start_requests(self):
        isbns = [
#            '0669326356',
             '080442957X',
#             '851310419',
#            '199957950X'
#            '0851310419'
        ]

        query = ("SELECT  AbeBooksCom_TaskTracking.isbn10 FROM AbeBooksCom_TaskTracking")
        self.cursor.execute(query)
        #isbns = self.cursor.fetchall()

        for isbn_row in self.cursor:
            isbn = isbn_row[0]
            url = 'https://www.abebooks.com/servlet/SearchResults?sts=t&cm_sp=SearchF-_-home-_-Results&sortby=17&an=&tn=&kn=&isbn={}'.format(isbn)
            yield scrapy.Request(url=url, callback=self.parse, 
                meta = {'isbn': isbn} ,
                cookies = {
                    'ab_optim': 'showA',
                    'selectedShippingRate': 'CAN',
                    'cmTPSet': 'Y',
                    'AbeShipTo': 'CAN',
                    'abe_vc': 17
                },
                headers = {'Referer': 'https://www.abebooks.com/?cm_sp=TopNav-_-Results-_-Logo'},
            )

    def parse(self, response):
        condition_labels = ['New', 'Used']

        isbn = response.meta['isbn']
        book_div_list = response.xpath('//div[contains(@class, "cf result")]')

        status = 200
        if len(book_div_list) == 0:
            status = -1
        sql = "UPDATE AbeBooksCom_TaskTracking set lastUpdated = utc_timestamp(), itemStatus = %s, lastUpdatedWSID = %s where isbn10 = %s"
        try:
            logging.info("isbn {} status {}".format(isbn, status))
            self.cursorInsert.execute(sql, (status,self.lastUpdatedWSID, isbn,))
            self.count_proc()
        except Exception as e:
            logging.error('Error at %s', 'division', exc_info=e)
            pass

        for book_div in book_div_list:
            result_detail_div = book_div.xpath('.//div[contains(@class, "result-detail")]')

            title = result_detail_div.xpath('./h2/a/span/text()').extract_first()
            bsa = result_detail_div.xpath('./div[@id="product-bsa"]/div/text()').extract()

            itemConditionLabel = ''
            itemConditionCode = 1 # For new
            coverLabel = ''

            for every_bsa in bsa:
                if every_bsa in condition_labels:
                    itemConditionLabel = every_bsa
                    if itemConditionLabel == 'Used':
                        itemConditionCode = 3
                else:
                    coverLabel = every_bsa

            # if len(bsa) >= 1:
            #     itemConditionLabel = bsa[0]
            # if len(bsa) >= 2:
            #     coverLabel = bsa[1]
            
            quantity_text = result_detail_div.xpath('./p[@id="quantity"]/text()').extract_first() # 'Quantity Available: 1'
            quantity = self.parse_price_str(quantity_text) # re.sub(r'[^0-9]', "", quantity_text)

            seller_div = result_detail_div.xpath('./div[contains(@class, "bookseller-info")]')
            seller = seller_div.xpath('./p[1]/a/text()').extract_first()            
            sellerLocation = seller_div.xpath('./p[1]/span/text()').extract_first()
            sellerLocation = re.sub(r'[\(\)]', "", sellerLocation)

            rating = seller_div.xpath('./p[2]/a/img/@alt').extract_first()
            rating = self.parse_price_str(rating) # re.sub(r'[^0-9]', "", rating)
            
            # get price

            buybox_div = book_div.xpath('.//div[contains(@class, "srp-item-buybox")]')
            book_price = buybox_div.xpath('.//div[@class="srp-item-price"]/text()').extract_first()
            book_price = self.parse_price_str(book_price) # re.sub(r'[^0-9\.]', "", book_price)
            shipping_price = buybox_div.xpath('.//span[@class="srp-item-price-shipping"]/text()').extract_first()
            if shipping_price:
                shipping_price = self.parse_price_str(shipping_price) # re.sub(r'[^0-9\.]', "", shipping_price)
            else:
                shipping_price = 0

            # destination
            buylink_list = buybox_div.xpath('.//a[@class="srp-item-buybox-link"]/@href').extract()
            # @TODO
            buylink = buylink_list[1]
            vid_groups = re.match(r'.*vid=(.*?)$', buylink)

            # itemConditionLabel
            itemConditionLabel = itemConditionLabel[0:10]
            coverLabel = coverLabel[0:10]
            if vid_groups:
                vid = vid_groups[1]
                shipRateUrl = 'https://www.abebooks.com/servlet/ShipRates?vid=' + vid

                item = AbeBook_Item()
                item['ISBN10'] = isbn
                item['itemPrice'] = book_price
                item['shippingPrice'] = shipping_price
                item['itemConditionLabel'] = itemConditionLabel
                item['itemConditionCode'] = itemConditionCode
                item['coverLabel'] = coverLabel
                item['qtyAvailable'] = quantity
                item['seller'] = seller
                item['sellerLocation'] = sellerLocation
                item['starRating'] = rating
                
                yield scrapy.Request(url=shipRateUrl, callback=self.parse_shipping, 
                    meta = {
                        'item': item
                    } ,
                    cookies = {
                        'ab_optim': 'showA',
                        'selectedShippingRate': 'CAN',
                        'cmTPSet': 'Y',
                        'AbeShipTo': 'CAN',
                        'abe_vc': 17
                    },
                    headers = {'Referer': response.request.url},
                )
            else:
                print ("no vid")     

        next_link = response.xpath('//a[@id="topbar-page-next"]')
        if next_link:
            rel_url = next_link.xpath('./@href').extract_first()
            url = 'https://www.abebooks.com' + rel_url
            yield scrapy.Request(url=url, callback=self.parse, 
                meta = {'isbn': isbn} ,
                cookies = {
                    'ab_optim': 'showA',
                    'selectedShippingRate': 'CAN',
                    'cmTPSet': 'Y',
                    'AbeShipTo': 'CAN',
                    'abe_vc': 17
                },
                headers = {'Referer': response.request.url},
            )
        pass

    def parse_shipping(self, response):
        item = response.meta['item']
        #file = open('3.html', 'w')
        #file.write(response.text)
        #file.close()

        # first business day
        shippingStandardSpeed = response.xpath('//table[@class="data"]//tr[1]/td[2]/text()').extract_first()
        match_groups = re.match(r'([0-9]+?)[ \-]+?([0-9]+?) ', shippingStandardSpeed)
        if match_groups:
            item['shippingStandardMinSpeed'] = match_groups[1]
            item['shippingStandardMaxSpeed'] = match_groups[2]

        # second business day
        shippingExpediateSpeed = response.xpath('//table[@class="data"]//tr[1]/td[2]/text()').extract_first()
        match_groups = re.match(r'([0-9]+?)[ \-]+?([0-9]+?) ', shippingExpediateSpeed)
        if match_groups:
            item['shippingExpediateMinSpeed'] = match_groups[1]
            item['shippingExpediateMaxSpeed'] = match_groups[2]

        # price
        shippingStandardFirst = response.xpath('//table[@class="data"]//tr[2]/td[2]/text()').extract_first()
        item['shippingStandardFirst'] = re.sub(r'[^0-9\.]', "", shippingStandardFirst)
        
        shippingStandardAdditional = response.xpath('//table[@class="data"]//tr[3]/td[2]/text()').extract_first()
        item['shippingStandardAdditional'] = re.sub(r'[^0-9\.]', "", shippingStandardAdditional)

        shippingExpediateFirst = response.xpath('//table[@class="data"]//tr[2]/td[3]/text()').extract_first()
        item['shippingExpediateFirst'] = re.sub(r'[^0-9\.]', "", shippingExpediateFirst)
        
        shippingExpediateAdditional = response.xpath('//table[@class="data"]//tr[3]/td[3]/text()').extract_first()
        item['shippingExpediateAdditional'] = re.sub(r'[^0-9\.]', "", shippingExpediateAdditional)
        
        now = datetime.utcnow()
        item['timestamp'] = now
        yield item

        sql = "CALL `insertAbeBooksCom`(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, utc_timestamp())"
        try:
            self.cursorInsert.execute(sql, (item['ISBN10'], item['itemPrice'], item['shippingPrice'], item['itemConditionLabel'], item['itemConditionCode'] , 
                item['coverLabel'], item['qtyAvailable'], item['seller'], item['sellerLocation'], item['starRating'], 
                item['shippingStandardFirst'], item['shippingStandardAdditional'], item['shippingStandardMinSpeed'], item['shippingExpediateMaxSpeed'], item['shippingExpediateFirst'], 
                item['shippingExpediateAdditional'], item['shippingExpediateMinSpeed'], item['shippingExpediateMaxSpeed'], self.lastUpdatedWSID))
            self.count_proc()
        except Exception as e:
            logging.error('Error at %s', 'division', exc_info=e)
            pass


    
