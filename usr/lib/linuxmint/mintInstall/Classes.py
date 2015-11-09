class Model:
    portals = []
    selected_category = None
    selected_application = None
    keyword = ""
    packages_to_install = []
    packages_to_remove = []
    filter_applications = "all"

    def __init__(self):
        portals = []
        selected_category = None
        selected_application = None
        keyword = ""
        packages_to_install = []
        packages_to_remove = []
        filter_applications = "all"

class Portal:
    key = ""
    name = ""
    link = ""
    release = ""
    release_name = ""
    update_url = ""
    categories = []
    items = []
    reviews = []

    def __init__(self, key, name="", link="", release="", release_name="", update_url=""):
        self.key = key
        self.name = name
        self.link = link
        self.release = release
        self.release_name = release_name
        self.update_url = update_url
        self.categories = []
        self.items = []
        self.reviews = []

    def find_category(self, key):
        for category in self.categories:
            if category.key == key:
                return category
        return None

    def find_item(self, key):
        for item in self.items:
            if item.key == key:
                return item
        return None

class Category:
    key = ""
    portal = None
    name = ""
    description = ""
    vieworder = 0
    parent = None
    subcategories = []
    items = []
    logo = None

    def __init__(self, portal, key, name="", description="", vieworder=0, parent=None, logo=None):
        self.key = key
        self.name = name
        self.description = description
        self.vieworder = vieworder
        self.parent = parent
        self.portal = portal
        self.subcategories = []
        self.items = []
        self.logo = logo

    def add_subcategory(self, category):
        self.subcategories.append(category)
        category.parent = self

    def add_item(self, item):
        self.items.append(item)
        item.category = self

class Item:
    key=""
    portal=None
    link=""
    mint_file=""
    category=""
    name=""
    description=""
    long_description=""
    added=""
    views=""
    license=""
    size=""
    website=""
    repository=""
    average_rating=""
    score = 0
    screenshot=None
    screenshot_url=None
    reviews = []
    packages = []
    repositories = []
    is_special = True
    status = "installed"
    version = ""

    def __init__(self, portal, key, link="", mint_file="", category="", name="", description="", long_description="", added="", views="", license="", size="", website="", repository="", average_rating=""):
        self.portal=portal
        self.key=key
        self.link=link
        self.mint_file=mint_file
        self.category=category
        self.name=name
        self.description=description
        self.long_description=long_description
        self.added=added
        self.views=views
        self.license=license
        self.size=size
        self.website=website
        self.repository=repository
        self.average_rating=average_rating
        self.screenshot=None
        self.screenshot_url=None
        self.score = 0
        self.reviews = []
        self.packages = []
        self.repositories = []
        self.is_special = True
        self.status = "installed"
        self.version = ""

    def add_review(self, review):
        self.reviews.append(review)
        review.item = self

class Review:
    portal=None
    user_id = ""
    username = ""
    item = None
    comment = ""
    rating = 3

    def __init__(self, portal, item, rating, comment, user_id, username):
        self.portal=portal
        self.item=item
        self.rating=rating
        self.comment=comment
        self.user_id=user_id
        self.username=username

