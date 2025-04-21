
// Create optimized data structures for city lookup
const cityIndex = new Map(); // For direct lookup
const cityNameList = []; // For fuzzy search
const stateMap = new Map(); // To map cities to states

// Common variants and misspellings of Indian cities
const cityVariants = {
  "belagavi": ["belgavi", "belagvi", "bilagavi", "belagavy", "belgaum", "belgam", "belgavi"],
  "bengaluru": ["bangalore", "bengluru", "benguluru", "bangalor", "bengalor"],
  "mumbai": ["bombay", "bambai", "bombai"],
  "kolkata": ["calcutta", "kolkota", "kalkota", "kolkatta"],
  "chennai": ["madras"],
  "kochi": ["cochin"],
  "thiruvananthapuram": ["trivandrum"],
  "pune": ["poona"],
  "ahmedabad": ["amdavad"],
  "coimbatore": ["kovai"],
  "varanasi": ["benares", "banaras"],
  "delhi": ["new delhi", "old delhi"],
  "hyderabad": ["secunderabad"]
};

const statesOfIndiaPart1 = [
    {
      state: "Andhra Pradesh",
      citiesAndTowns: [
        "Vijayawada", "Bezawada", "Visakhapatnam", "Vizag", "Guntur", "Tirupati", "Kurnool",
        "Rajahmundry", "Rajamahendravaram", "Nellore", "Kakinada", "Amaravati", "Anantapur",
        "Kadapa", "Cuddapah", "Srikakulam", "Machilipatnam", "Masulipatnam", "Chittoor",
        "Ongole", "Eluru", "Tenali", "Bhimavaram", "Proddatur", "Hindupur", "Tadepalligudem",
        "Madanapalle", "Gudivada", "Narasaraopet", "Chilakaluripet", "Adoni", "Tadpatri",
        "Dharmavaram", "Palakollu", "Nandyal", "Puttur", "Vinukonda", "Rayachoti", "Kovvur",
        "Amalapuram", "Sullurpeta", "Jammalamadugu", "Peddapuram", "Punganur", "Nidadavole",
        "Tanuku", "Markapur", "Chirala", "Kandukur", "Bobbili", "Parvathipuram", "Salur",
        "Mandapeta", "Palasa", "Tuni", "Samalkot", "Pithapuram", "Repalle", "Nuzvid",
        "Guntakal", "Rayadurg", "Naidupeta", "Venkatagiri", "Badvel", "Nagari", "Gudur",
        "Atmakur", "Addanki", "Macherla", "Bapatla", "Pedana", "Yemmiganur", "Kadiri",
        "Kanigiri", "Kavali", "Narasapuram", "Pulivendula", "Srisailam", "Tekkali", "Ichchapuram",
        "Palamaner", "Pakala", "Vuyyuru", "Tiruvuru", "Akividu", "Jaggayyapeta", "Gannavaram",
        "Polavaram", "Ramachandrapuram", "Sattenapalle", "Yanam", 
        "Tadimeti", "Mangalagiri", "Srikalahasti", "Tadipatri", "Dhone", "Mancherial", 
        "Puttaparthi", "Pamuru", "Giddalur", "Narsipatnam", "Palakonda", "Parvathipuram Manyam", 
        "Narsapur", "West Godavari", "Singarayakonda", "Darsi", "Ponnur", "Nandigama", 
        "Rajam", "Kondapalli", "Tiruvuru Town", "Nellore City", "Nellore Rural", "Gajuwaka", 
        "Anakapalle", "Bheemunipatnam", "Tagarapuvalasa", "Penukonda", "Dharmavaram City", 
        "Rajampet", "Mydukur", "Kamalapuram", "Yerraguntla", "Bodhan", "Yanamalakuduru", 
        "Pedakakani", "Vinukonda Town", "Kondapalle", "Kadiri Town", "Rajampeta", "Rayachoti City", 
        "Chennur", "Venkatagiri Town", "Piduguralla", "Martur", "Gurazala", "Nandikotkur", 
        "Bethamcherla", "Mantralayam", "Adoni City", "Gooty", "Kalyanadurgam", "Kadapa City"
      ]
    },
    {
      state: "Arunachal Pradesh",
      citiesAndTowns: [
        "Itanagar", "Naharlagun", "Pasighat", "Tawang", "Ziro", "Bomdila", "Tezu", "Roing",
        "Aalo", "Along", "Daporijo", "Yingkiong", "Khonsa", "Changlang", "Namsai", "Seppa",
        "Anini", "Hawai", "Longding", "Miao", "Bordumsa", "Jairampur", "Dirang", "Raga",
        "Basar", "Deomali", "Koloriang", "Nari", "Pangin", "Tuting", "Bhalukpong", "Sagalee",
        "Dambuk", "Mechukha", "Hayuliang", "Wakka", "Nampong", "Lazu", "Tali", "Nyapin",
        "Parsi-Parlo", "Bameng", "Chayangtajo", "Taliha", "Nacho", "Vijoynagar", "Pidia",
        "Monigong", "Kimin", "Borduria", "Manmao", "Wakro", "Tezu Town", "Chowkham",
        "Boleng", "Yazali", "Diyun", "Likabali", "Rumgong", "Liromoba",
        "Itanagar Capital Complex", "Pasighat Town", "Yomcha", "Siyum", "Payum", "Tato", 
        "Lower Siang", "Dumporijo", "Riga", "Gensi", "Likabali Town", "Zero", "Zero Valley", 
        "Happy Valley", "Sagalee Town", "Lower Subansiri", "Bame", "Doimukh", "Yupia", 
        "Pappu Valley", "Kimin Town", "Tawang Monastery", "Zemithang", "Lumla", "Jang", 
        "Namsai Town", "Upper Subansiri", "Upper Siang", "West Kameng", "East Kameng", 
        "Pakke-Kessang", "Leporiang", "Palin", "Aalo Town", "Mechuka Valley", "Tuting Town", 
        "Gelling", "Singa", "Tawang City", "East Siang", "West Siang", "Pasighat City", 
        "Dirang Valley", "Kalaktang", "Nafra", "Bomdila Town", "Thrizino", "Rupa", 
        "Tenga Valley", "Miao Town", "Kharsang", "Namphai", "Vijoynagar Valley"
      ]
    },
    {
      state: "Assam",
      citiesAndTowns: [
        "Guwahati", "Gauhati", "Dibrugarh", "Silchar", "Jorhat", "Nagaon", "Nowgong", "Tezpur",
        "Tinsukia", "Sivasagar", "Sibsagar", "Bongaigaon", "Goalpara", "Barpeta", "Kokrajhar",
        "Dhubri", "Hojai", "Diphu", "North Lakhimpur", "Karimganj", "Golaghat", "Hailakandi",
        "Mangaldoi", "Dhemaji", "Biswanath Chariali", "Pathsala", "Rangia", "Margherita",
        "Duliajan", "Digboi", "Sonari", "Moranhat", "Nazira", "Lanka", "Lumding", "Badarpur",
        "Chapar", "Gohpur", "Jonai", "Sualkuchi", "Palasbari", "Hatsingimari", "Dhing",
        "Morigaon", "Udalguri", "Tangla", "Bihpuria", "Dhekiajuli", "Bilasipara", "Kharupetia",
        "Gossaigaon", "Makum", "Doom Dooma", "Sadiya", "Lakhipur", "Raha", "Jamugurihat",
        "Howly", "Barama", "Abhayapuri", "Bokakhat", "Dergaon", "Dhakuakhana", "Chabua",
        "Hajo", "Rangapara", "Sarupathar", "Gauripur", "Baihata Chariali", "Nalbari",
        "Tihu", "Bijni", "Silapathar", "Basugaon", "Bokajan", "Namrup", "Amguri",
        "Guwahati City", "Dibrugarh City", "Silchar City", "Jorhat City", "Tezpur City", 
        "Dispur", "Jalukbari", "Maligaon", "Bharalumukh", "Ganeshguri", "Azara", "Beltola", 
        "Narengi", "Chandmari", "Paltan Bazar", "Fancy Bazar", "Pan Bazar", "Athgaon", 
        "Ulubari", "Ambari", "Six Mile", "Khanapara", "Amingaon", "Mirza", "Nagaon City", 
        "Jorhat Town", "Tezpur Town", "Barpeta Town", "Sibsagar Town", "North Guwahati", 
        "Narayanpur", "Mangaldai Town", "Sarthebari", "Bajali", "Tamulpur", "Dudhnoi", 
        "Tangla Town", "Goreswar", "Dimakuchi", "Kalaigaon", "Patharkandi", "Kampur", 
        "Hojai Town", "Doboka", "Kaki", "Rupahi", "Titabor", "Mariani", "Teok", "Majuli", 
        "Dhakuakhana Town", "Bogibeel", "Chapakhowa", "Namsai", "Biswanath Town", "Sapatgram", 
        "Bilasipara Town", "Bijni Town", "Barpeta Road", "Sorbhog", "Bihpuria Town", 
        "Sipajhar", "Tamulpur", "Kakopathar", "Margherita Town", "Doomdooma Town", "Naharkatia"
      ]
    },
    {
      state: "Bihar",
      citiesAndTowns: [
        "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga", "Purnia", "Purnea",
        "Bihar Sharif", "Aurangabad", "Arrah", "Ara", "Begusarai", "Katihar", "Chapra",
        "Chhapra", "Sasaram", "Hajipur", "Motihari", "Siwan", "Bettiah", "Samastipur",
        "Sitamarhi", "Madhubani", "Buxar", "Jehanabad", "Jamui", "Supaul", "Saharsa",
        "Kishanganj", "Dehri", "Bagaha", "Munger", "Nawada", "Araria", "Forbesganj",
        "Gopalganj", "Khagaria", "Madhepura", "Sheikhpura", "Lakhisarai", "Raxaul",
        "Barh", "Bikramganj", "Mokama", "Masaurhi", "Hilsa", "Rajgir", "Bhabua", "Sheohar",
        "Sherghati", "Banmankhi", "Baruni", "Dumraon", "Jhajha", "Kahalgaon", "Maner",
        "Naugachia", "Phulwari Sharif", "Teghra", "Amarpur", "Banka", "Barhiya", "Barauni",
        "Dalsinghsarai", "Fatwah", "Hisua", "Islampur", "Jhanjharpur", "Kharagpur",
        "Lalganj", "Maharajganj", "Mairwa", "Makhdumpur", "Nabinagar", "Ramnagar",
        "Rosera", "Sultanganj", "Warsaliganj", "Asarganj", "Bikram", "Colgong", "Ghoghardiha",
        "Jainagar", "Kasba", "Katoria", "Parsa", "Pipra", "Sonepur", "Tarapur",
        "Patna City", "Patna Sahib", "Bakhtiarpur", "Danapur", "Khusrupur", "Maner Town", 
        "Nohsa", "Phulwari", "Pataliputra", "Digha", "Danapur Cantonment", "Fatuha", 
        "Paliganj", "Punpun", "Bihta", "Barh Town", "Nawada City", "Gaya City", "Bodh Gaya", 
        "Lakhisarai Town", "Muzaffarpur City", "Bhagalpur City", "Darbhanga City", 
        "Buxar Town", "Dehri-on-Sone", "Sasaram City", "Aurangabad City", "Arrah City", 
        "Jehanabad City", "Sitamarhi City", "Motihari City", "Bagaha City", "Bettiah City", 
        "Katihar City", "Purnia City", "Dalsingh Sarai", "Samastipur City", "Hajipur City", 
        "Chhapra City", "Siwan City", "Gopalganj City", "Forbesganj City", "Madhubani City", 
        "Saharsa City", "Supaul City", "Kishanganj City", "Jamui City", "Araria City", 
        "Madhepura City", "Begusarai City", "Munger City", "Kaimur", "Rohtas", "Bhojpur"
      ]
    },
    {
      state: "Chhattisgarh",
      citiesAndTowns: [
        "Raipur", "Bhilai", "Durg", "Bilaspur", "Korba", "Jagdalpur", "Raigarh", "Ambikapur",
        "Dhamtari", "Mahasamund", "Rajnandgaon", "Kanker", "Janjgir", "Bemetara", "Kawardha",
        "Champa", "Baloda Bazar", "Sakti", "Mungeli", "Sarangarh", "Balod", "Dongargarh",
        "Khairagarh", "Narayanpur", "Kondagaon", "Bhanupratappur", "Pandariya", "Tilda",
        "Arang", "Abhanpur", "Gariaband", "Kurud", "Mana", "Simga", "Bhatapara", "Pendra",
        "Gaurela", "Marwahi", "Lormi", "Kota", "Takhatpur", "Pathalgaon", "Jashpur",
        "Bagicha", "Farsabahar", "Manendragarh", "Baikunthpur", "Surajpur", "Pratappur",
        "Bhaiyathan", "Odgi", "Ramanujganj", "Wadrafnagar", "Balrampur", "Rajpur",
        "Sitapur", "Katghora", "Pali", "Pasan", "Akaltara", "Naila", "Saraipali", "Basna",
        "Pithora", "Kharsia", "Dharamjaigarh", "Lailunga", "Gharghoda", "Bhatgaon",
        "Chirmiri", "Dipka", "Pandaria", "Saja", "Berla", "Dondi", "Dalli-Rajhara",
        "Raipur City", "Bhilai City", "Durg City", "Bilaspur City", "Korba City", "Jagdalpur City", 
        "Raigarh City", "Ambikapur City", "Dhamtari City", "Mahasamund City", "Rajnandgaon City", 
        "Kanker City", "Janjgir City", "Bemetara City", "Kawardha City", "Champa City", 
        "Baloda Bazar City", "Sakti City", "Mungeli City", "Sarangarh City", "Balod City", 
        "Dongargarh City", "Khairagarh City", "Narayanpur City", "Kondagaon City", 
        "Bhanupratappur City", "Pandariya City", "Tilda City", "Arang City", "Abhanpur City", 
        "Gariaband City", "Kurud City", "Mana City", "Simga City", "Bhatapara City", 
        "Pendra City", "Gaurela City", "Marwahi City", "Lormi City", "Kota City", 
        "Takhatpur City", "Pathalgaon City", "Jashpur City", "Bagicha City", "Farsabahar City", 
        "Manendragarh City", "Baikunthpur City", "Surajpur City", "Pratappur City", 
        "Bhaiyathan City", "Odgi City", "Ramanujganj City", "Wadrafnagar City", "Balrampur City", 
        "Rajpur City", "Sitapur City", "Katghora City", "Pali City", "Pasan City", "Akaltara City", 
        "Naila City", "Saraipali City", "Basna City", "Pithora City", "Kharsia City", 
        "Dharamjaigarh City", "Lailunga City", "Gharghoda City", "Bhatgaon City", "Chirmiri City", 
        "Dipka City", "Pandaria City", "Saja City", "Berla City", "Dondi City", "Dalli-Rajhara City"
      ]
    },
    {
      state: "Goa",
      citiesAndTowns: [
        "Panaji", "Panjim", "Margao", "Madgaon", "Vasco da Gama", "Mapusa", "Ponda",
        "Bicholim", "Curchorem", "Sanguem", "Valpoi", "Canacona", "Quepem", "Sanquelim",
        "Cuncolim", "Chaudi", "Pernem", "Siolim", "Calangute", "Aldona", "Chinchinim",
        "Dabolim", "Mormugao", "Sancoale", "Cortalim", "Colva", "Benaulim", "Varca",
        "Majorda", "Candolim", "Anjuna", "Arambol", "Morjim", "Saligao", "Assagao",
        "Caranzalem", "Taleigao", "Santa Cruz", "Bambolim", "Chicalim", "Verna",
        "Shiroda", "Loutolim", "Raia", "Curtorim", "Sao Jose de Areal", "Dharbandora",
        "Mollem", "Sanvordem", "Colvale", "Reis Magos", "Navelim", "Velim",
        "Panaji City", "Margao City", "Vasco City", "Mapusa City", "Ponda City", "Bicholim City", 
        "Curchorem City", "Sanguem City", "Valpoi City", "Canacona City", "Quepem City", 
        "Sanquelim City", "Cuncolim City", "Chaudi City", "Pernem City", "Siolim City", 
        "Calangute City", "Aldona City", "Chinchinim City", "Dabolim City", "Mormugao City", 
        "Sancoale City", "Cortalim City", "Colva City", "Benaulim City", "Varca City", 
        "Majorda City", "Candolim City", "Anjuna City", "Arambol City", "Morjim City", 
        "Saligao City", "Assagao City", "Caranzalem City", "Taleigao City", "Santa Cruz City", 
        "Bambolim City", "Chicalim City", "Verna City", "Shiroda City", "Loutolim City", 
        "Raia City", "Curtorim City", "Sao Jose de Areal City", "Dharbandora City", 
        "Mollem City", "Sanvordem City", "Colvale City", "Reis Magos City", "Navelim City", 
        "Velim City"
      ]
    },
    {
      state: "Gujarat",
      citiesAndTowns: [
        "Ahmedabad", "Surat", "Vadodara", "Baroda", "Rajkot", "Bhavnagar", "Jamnagar",
        "Gandhinagar", "Junagadh", "Anand", "Nadiad", "Mehsana", "Porbandar", "Navsari",
        "Bharuch", "Broach", "Surendranagar", "Godhra", "Palanpur", "Patan", "Morbi",
        "Veraval", "Botad", "Gondal", "Jetpur", "Kalol", "Deesa", "Dahod", "Keshod",
        "Wankaner", "Ankleshwar", "Bardoli", "Himatnagar", "Vyara", "Unjha", "Visnagar",
        "Sidhpur", "Mangrol", "Dhoraji", "Amreli", "Kadi", "Dholka", "Vapi", "Valsad",
        "Gariadhar", "Kodinar", "Upleta", "Sihor", "Petlad", "Kapadvanj", "Modasa",
        "Chhota Udaipur", "Khambhat", "Cambay", "Dabhoi", "Padra", "Lunawada", "Sanand",
        "Thangadh", "Wadhwan", "Radhanpur", "Vijapur", "Kheralu", "Mansa", "Savarkundla",
        "Halvad", "Rajula", "Mahuva", "Talaja", "Una", "Mandvi", "Salaya", "Jodia",
        "Dwarka", "Okha", "Bhuj", "Anjar", "Gandhidham", "Mundra", "Adipur", "Nakhatrana",
        "Rapar", "Kutch Mandvi", "Bhanvad", "Jamjodhpur", "Lathi", "Paddhari",
        "Ahmedabad City", "Surat City", "Vadodara City", "Rajkot City", "Bhavnagar City", 
        "Jamnagar City", "Gandhinagar City", "Junagadh City", "Anand City", "Nadiad City", 
        "Mehsana City", "Porbandar City", "Navsari City", "Bharuch City", "Surendranagar City", 
        "Godhra City", "Palanpur City", "Patan City", "Morbi City", "Veraval City", "Botad City", 
        "Gondal City", "Jetpur City", "Kalol City", "Deesa City", "Dahod City", "Keshod City", 
        "Wankaner City", "Ankleshwar City", "Bardoli City", "Himatnagar City", "Vyara City", 
        "Unjha City", "Visnagar City", "Sidhpur City", "Mangrol City", "Dhoraji City", 
        "Amreli City", "Kadi City", "Dholka City", "Vapi City", "Valsad City", "Gariadhar City", 
        "Kodinar City", "Upleta City", "Sihor City", "Petlad City", "Kapadvanj City", 
        "Modasa City", "Chhota Udaipur City", "Khambhat City", "Dabhoi City", "Padra City", 
        "Lunawada City", "Sanand City", "Thangadh City", "Wadhwan City", "Radhanpur City", 
        "Vijapur City", "Kheralu City", "Mansa City", "Savarkundla City", "Halvad City", 
        "Rajula City", "Mahuva City", "Talaja City", "Una City", "Mandvi City", "Salaya City", 
        "Jodia City", "Dwarka City", "Okha City", "Bhuj City", "Anjar City", "Gandhidham City", 
        "Mundra City", "Adipur City", "Nakhatrana City", "Rapar City", "Kutch Mandvi City", 
        "Bhanvad City", "Jamjodhpur City", "Lathi City", "Paddhari City"
      ]
    },
    {
      state: "Haryana",
      citiesAndTowns: [
        "Gurugram", "Gurgaon", "Faridabad", "Hisar", "Panipat", "Karnal", "Rohtak", "Ambala",
        "Yamunanagar", "Sonipat", "Sonepat", "Panchkula", "Rewari", "Bhiwani", "Jind",
        "Sirsa", "Kaithal", "Kurukshetra", "Bahadurgarh", "Fatehabad", "Palwal", "Narnaul",
        "Gohana", "Hansi", "Tohana", "Narwana", "Charkhi Dadri", "Mahendragarh", "Thanesar",
        "Pehowa", "Ladwa", "Safidon", "Kalayat", "Rania", "Ellenabad", "Mandawar",
        "Pinjore", "Kalka", "Radaur", "Indri", "Nilokheri", "Assandh", "Ganaur", "Samalkha",
        "Barwala", "Nuh", "Ferozepur Jhirka", "Taoru", "Pataudi", "Hodal", "Kosli",
        "Bawal", "Loharu", "Siwani", "Tosham", "Ateli", "Kanina", "Nangal Chaudhary",
        "Berikhera", "Uchana", "Gharaunda", "Israna", "Madlauda", "Bilaspur", "Shahbad",
        "Jakhal Mandi", "Pundri", "Ratia", "Kalanaur", "Sohna", "Hathin", "Punhana",
        "Chhachhrauli", "Sadhaura", "Naraingarh", "Kharkhoda", "Maham", "Meham",
        "Gurugram City", "Faridabad City", "Hisar City", "Panipat City", "Karnal City", 
        "Rohtak City", "Ambala City", "Yamunanagar City", "Sonipat City", "Panchkula City", 
        "Rewari City", "Bhiwani City", "Jind City", "Sirsa City", "Kaithal City", 
        "Kurukshetra City", "Bahadurgarh City", "Fatehabad City", "Palwal City", "Narnaul City", 
        "Gohana City", "Hansi City", "Tohana City", "Narwana City", "Charkhi Dadri City", 
        "Mahendragarh City", "Thanesar City", "Pehowa City", "Ladwa City", "Safidon City", 
        "Kalayat City", "Rania City", "Ellenabad City", "Mandawar City", "Pinjore City", 
        "Kalka City", "Radaur City", "Indri City", "Nilokheri City", "Assandh City", 
        "Ganaur City", "Samalkha City", "Barwala City", "Nuh City", "Ferozepur Jhirka City", 
        "Taoru City", "Pataudi City", "Hodal City", "Kosli City", "Bawal City", "Loharu City", 
        "Siwani City", "Tosham City", "Ateli City", "Kanina City", "Nangal Chaudhary City", 
        "Berikhera City", "Uchana City", "Gharaunda City", "Israna City", "Madlauda City", 
        "Bilaspur City", "Shahbad City", "Jakhal Mandi City", "Pundri City", "Ratia City", 
        "Kalanaur City", "Sohna City", "Hathin City", "Punhana City", "Chhachhrauli City", 
        "Sadhaura City", "Naraingarh City", "Kharkhoda City", "Maham City", "Meham City"
      ]
    },
    {
      state: "Himachal Pradesh",
      citiesAndTowns: [
        "Shimla", "Simla", "Dharamshala", "Mandi", "Solan", "Kullu", "Manali", "Bilaspur",
        "Hamirpur", "Una", "Chamba", "Nahan", "Palampur", "Kangra", "Keylong", "Reckong Peo",
        "Sundernagar", "Paonta Sahib", "Jogindernagar", "Nurpur", "Dalhousie", "Rampur",
        "Rohru", "Theog", "Kasauli", "Arki", "Baddi", "Nalagarh", "Parwanoo", "Ghumarwin",
        "Sarkaghat", "Baijnath", "Tira Sujanpur", "Jawalamukhi", "Nadaun", "Dehra", "Gohar",
        "Karsog", "Banjar", "Ani", "Lahaul", "Spiti", "Bhuntar", "Naggar", "Jubbal",
        "Kotkhai", "Chopal", "Rajgarh", "Sangla", "Tabo", "Kalpa", "Pooh", "Suni",
        "Kumarsain", "Nankhari", "Sandhol", "Dharampur", "Barsar", "Jaisinghpur",
        "Shahpur", "Nagrota Bagwan", "Ranital", "Haripur", "Santokhgarh", "Mehatpur",
        "Tahlwal", "Gagret", "Daulatpur", "Talai", "Pandoh", "Rewalsar", "Nerchowk",
        "Shimla City", "Dharamshala City", "Mandi City", "Solan City", "Kullu City", 
        "Manali City", "Bilaspur City", "Hamirpur City", "Una City", "Chamba City", 
        "Nahan City", "Palampur City", "Kangra City", "Keylong City", "Reckong Peo City", 
        "Sundernagar City", "Paonta Sahib City", "Jogindernagar City", "Nurpur City", 
        "Dalhousie City", "Rampur City", "Rohru City", "Theog City", "Kasauli City", 
        "Arki City", "Baddi City", "Nalagarh City", "Parwanoo City", "Ghumarwin City", 
        "Sarkaghat City", "Baijnath City", "Tira Sujanpur City", "Jawalamukhi City", 
        "Nadaun City", "Dehra City", "Gohar City", "Karsog City", "Banjar City", "Ani City", 
        "Lahaul City", "Spiti City", "Bhuntar City", "Naggar City", "Jubbal City", 
        "Kotkhai City", "Chopal City", "Rajgarh City", "Sangla City", "Tabo City", 
        "Kalpa City", "Pooh City", "Suni City", "Kumarsain City", "Nankhari City", 
        "Sandhol City", "Dharampur City", "Barsar City", "Jaisinghpur City", "Shahpur City", 
        "Nagrota Bagwan City", "Ranital City", "Haripur City", "Santokhgarh City", 
        "Mehatpur City", "Tahlwal City", "Gagret City", "Daulatpur City", "Talai City", 
        "Pandoh City", "Rewalsar City", "Nerchowk City"
      ]
    },
    {
      state: "Jharkhand",
      citiesAndTowns: [
        "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro Steel City", "Deoghar", "Hazaribagh",
        "Giridih", "Ramgarh", "Phusro", "Dumka", "Medininagar", "Daltonganj", "Chaibasa",
        "Jhumri Telaiya", "Sahibganj", "Chatra", "Kodarma", "Gumla", "Lohardaga", "Simdega",
        "Pakur", "Garhwa", "Latehar", "Barhi", "Chakradharpur", "Khunti", "Bundu", "Rajmahal",
        "Jharia", "Nirsa", "Chirkunda", "Mihijam", "Bermo", "Gobindpur", "Tenughat",
        "Jasidih", "Madhupur", "Patratu", "Barughutu", "Chandil", "Silli", "Mandu",
        "Topchanchi", "Baghmara", "Tisri", "Chandwa", "Hussainabad", "Bishrampur",
        "Kanke", "Ormanjhi", "Kedla", "Sarath", "Gomoh", "Katras", "Jhinkpani", "Noamundi",
        "Kiriburu", "Meghahatuburu", "Jugsalai", "Chas", "Basia", "Panki", "Kuru",
        "Chainpur", "Barkatha", "Domchanch", "Markacho", "Bagodar", "Jainagar", "Bhurkunda",
        "Saunda", "Khalari", "Tandwa", "Lapanga", "Rania", "Barwadih", "Mahagama","Mango",
        "Ranchi City", "Jamshedpur City", "Dhanbad City", "Bokaro City", "Deoghar City", 
        "Hazaribagh City", "Giridih City", "Ramgarh City", "Phusro City", "Dumka City", 
        "Medininagar City", "Daltonganj City", "Chaibasa City", "Jhumri Telaiya City", 
        "Sahibganj City", "Chatra City", "Kodarma City", "Gumla City", "Lohardaga City", 
        "Simdega City", "Pakur City", "Garhwa City", "Latehar City", "Barhi City", 
        "Chakradharpur City", "Khunti City", "Bundu City", "Rajmahal City", "Jharia City", 
        "Nirsa City", "Chirkunda City", "Mihijam City", "Bermo City", "Gobindpur City", 
        "Tenughat City", "Jasidih City", "Madhupur City", "Patratu City", "Barughutu City", 
        "Chandil City", "Silli City", "Mandu City", "Topchanchi City", "Baghmara City", 
        "Tisri City", "Chandwa City", "Hussainabad City", "Bishrampur City", "Kanke City", 
        "Ormanjhi City", "Kedla City", "Sarath City", "Gomoh City", "Katras City", 
        "Jhinkpani City", "Noamundi City", "Kiriburu City", "Meghahatuburu City", 
        "Jugsalai City", "Chas City", "Basia City", "Panki City", "Kuru City", "Chainpur City", 
        "Barkatha City", "Domchanch City", "Markacho City", "Bagodar City", "Jainagar City", 
        "Bhurkunda City", "Saunda City", "Khalari City", "Tandwa City", "Lapanga City", 
        "Rania City", "Barwadih City", "Mahagama City", "Mango City"
      ]
    },
    {
      state: "Karnataka",
      citiesAndTowns: [
        "Bengaluru", "Bangalore", "Mysuru", "Mysore", "Hubli", "Hubballi", "Belagavi", "Belgaum",
        "Mangaluru", "Mangalore", "Davanagere", "Shimoga", "Shivamogga", "Tumakuru", "Tumkur",
        "Bijapur", "Vijayapura", "Bellary", "Ballari", "Udupi", "Hassan", "Gulbarga",
        "Kalaburagi", "Raichur", "Chitradurga", "Kolar", "Bidar", "Bagalkot", "Hospet",
        "Gadag", "Chikmagalur", "Mandya", "Channapatna", "Ramanagara", "Sira", "Sindhanur",
        "Tiptur", "Arsikere", "Nanjangud", "Gokak", "Koppal", "Yadgir", "Sakleshpur",
        "Haveri", "Ranebennur", "Chintamani", "Hunsur", "Robertsonpet", "Dharwad",
        "Sirsi", "Karwar", "Gangavati", "Harihar", "Athani", "Saundatti", "Jamkhandi",
        "Mudhol", "Ilkal", "Rabkavi Banhatti", "Humnabad", "Shahapur", "Shorapur",
        "Sedam", "Kundgol", "Navalgund", "Nargund", "Savanur", "Byadgi", "Hangal",
        "Shiggaon", "Mundargi", "Lingsugur", "Manvi", "Devadurga", "Hirekerur", "Honnali",
        "Channagiri", "Holalkere", "Hoskote", "Malur", "K R Puram", "Magadi", "Nelamangala",
        "Pavagada", "Koratagere", "Madhugiri", "Gauribidanur", "Chikballapur", "Sidlaghatta",
        "Bagepalli", "Srinivaspur", "Mulbagal", "Bangarapet", "KGF", "Kolar Gold Fields",
        "Bengaluru City", "Mysuru City", "Hubli City", "Belagavi City", "Mangaluru City", 
        "Davanagere City", "Shimoga City", "Tumakuru City", "Bijapur City", "Bellary City", 
        "Udupi City", "Hassan City", "Gulbarga City", "Raichur City", "Chitradurga City", 
        "Kolar City", "Bidar City", "Bagalkot City", "Hospet City", "Gadag City", 
        "Chikmagalur City", "Mandya City", "Channapatna City", "Ramanagara City", "Sira City", 
        "Sindhanur City", "Tiptur City", "Arsikere City", "Nanjangud City", "Gokak City", 
        "Koppal City", "Yadgir City", "Sakleshpur City", "Haveri City", "Ranebennur City", 
        "Chintamani City", "Hunsur City", "Robertsonpet City", "Dharwad City", "Sirsi City", 
        "Karwar City", "Gangavati City", "Harihar City", "Athani City", "Saundatti City", 
        "Jamkhandi City", "Mudhol City", "Ilkal City", "Rabkavi Banhatti City", "Humnabad City", 
        "Shahapur City", "Shorapur City", "Sedam City", "Kundgol City", "Navalgund City", 
        "Nargund City", "Savanur City", "Byadgi City", "Hangal City", "Shiggaon City", 
        "Mundargi City", "Lingsugur City", "Manvi City", "Devadurga City", "Hirekerur City", 
        "Honnali City", "Channagiri City", "Holalkere City", "Hoskote City", "Malur City", 
        "K R Puram City", "Magadi City", "Nelamangala City", "Pavagada City", "Koratagere City", 
        "Madhugiri City", "Gauribidanur City", "Chikballapur City", "Sidlaghatta City", 
        "Bagepalli City", "Srinivaspur City", "Mulbagal City", "Bangarapet City", "KGF City", 
        "Kolar Gold Fields City"
      ]
    },
    {
      state: "Kerala",
      citiesAndTowns: [
        "Thiruvananthapuram", "Trivandrum", "Kochi", "Cochin", "Kozhikode", "Calicut",
        "Thrissur", "Kollam", "Quilon", "Kannur", "Cannanore", "Alappuzha", "Alleppey",
        "Kottayam", "Palakkad", "Palghat", "Malappuram", "Kasaragod", "Pathanamthitta",
        "Idukki", "Wayanad", "Ponnani", "Tirur", "Manjeri", "Thalassery", "Tellicherry",
        "Payyannur", "Kanhangad", "Nileshwaram", "Feroke", "Mavelikkara", "Chengannur",
        "Attingal", "Neyyattinkara", "Kayamkulam", "Adoor", "Kodungallur", "Chavakkad",
        "Perinthalmanna", "Varkala", "Paravur", "Mattannur", "Vadakara", "Badagara",
        "Koyilandy", "Quilandy", "Mukkam", "Iritty", "Panoor", "Kalpetta", "Mananthavady",
        "Sultan Bathery", "Nedumangad", "Kilimanoor", "Kattappana", "Thodupuzha", "Muvattupuzha",
        "Perumbavoor", "Angamaly", "Chalakudy", "Irinjalakuda", "Kunnamkulam", "Guruvayur",
        "Ottappalam", "Shoranur", "Cherpulassery", "Mannarkkad", "Kondotty", "Tirurangadi",
        "Kottakkal", "Valanchery", "Tanur", "Parappanangadi", "Ponnani", "Punalur",
        "Karunagappally", "Changanassery", "Kanjirappally", "Pala", "Vaikom", "Piravom",
        "Kothamangalam", "North Paravur", "Aluva", "Edappally", "Fort Kochi",
        "Thiruvananthapuram City", "Kochi City", "Kozhikode City", "Thrissur City", 
        "Kollam City", "Kannur City", "Alappuzha City", "Kottayam City", "Palakkad City", 
        "Malappuram City", "Kasaragod City", "Pathanamthitta City", "Idukki City", 
        "Wayanad City", "Ponnani City", "Tirur City", "Manjeri City", "Thalassery City", 
        "Payyannur City", "Kanhangad City", "Nileshwaram City", "Feroke City", "Mavelikkara City", 
        "Chengannur City", "Attingal City", "Neyyattinkara City", "Kayamkulam City", 
        "Adoor City", "Kodungallur City", "Chavakkad City", "Perinthalmanna City", 
        "Varkala City", "Paravur City", "Mattannur City", "Vadakara City", "Koyilandy City", 
        "Mukkam City", "Iritty City", "Panoor City", "Kalpetta City", "Mananthavady City", 
        "Sultan Bathery City", "Nedumangad City", "Kilimanoor City", "Kattappana City", 
        "Thodupuzha City", "Muvattupuzha City", "Perumbavoor City", "Angamaly City", 
        "Chalakudy City", "Irinjalakuda City", "Kunnamkulam City", "Guruvayur City", 
        "Ottappalam City", "Shoranur City", "Cherpulassery City", "Mannarkkad City", 
        "Kondotty City", "Tirurangadi City", "Kottakkal City", "Valanchery City", "Tanur City", 
        "Parappanangadi City", "Ponnani City", "Punalur City", "Karunagappally City", 
        "Changanassery City", "Kanjirappally City", "Pala City", "Vaikom City", "Piravom City", 
        "Kothamangalam City", "North Paravur City", "Aluva City", "Edappally City", 
        "Fort Kochi City"
      ]
    },
    {
      state: "Madhya Pradesh",
      citiesAndTowns: [
        "Bhopal", "Indore", "Jabalpur", "Jubbulpore", "Gwalior", "Ujjain", "Sagar", "Rewa",
        "Satna", "Ratlam", "Dewas", "Khandwa", "Burhanpur", "Chhindwara", "Mandsaur",
        "Morena", "Vidisha", "Hoshangabad", "Betul", "Damoh", "Katni", "Shivpuri", "Neemuch",
        "Chhatarpur", "Pithampur", "Sehore", "Khargone", "Itarsi", "Seoni", "Balaghat",
        "Ashoknagar", "Tikamgarh", "Shahdol", "Singrauli", "Guna", "Barwani", "Harda",
        "Mandla", "Dindori", "Sidhi", "Umaria", "Narsinghpur", "Raisen", "Dhar", "Alirajpur",
        "Jhabua", "Shajapur", "Rajgarh", "Sheopur", "Anuppur", "Agar", "Sendhwa", "Pandhurna",
        "Waraseoni", "Pipariya", "Sarni", "Sohagpur", "Multai", "Amla", "Barwaha",
        "Sanawad", "Mandideep", "Biaora", "Gadarwara", "Kukshi", "Manawar", "Maheshwar",
        "Omkareshwar", "Nagda", "Tarana", "Susner", "Nalkheda", "Badnagar", "Khachrod",
        "Jaora", "Mhow", "Dr. Ambedkar Nagar", "Depalpur", "Khilchipur", "Sarangpur",
        "Ashta", "Ichhawar", "Nasrullaganj", "Budhni", "Rehti", "Shahpur", "Badi",
        "Kurwai", "Lateri", "Sironj", "Shamgarh", "Pachore", "Bhanpura",
        "Bhopal City", "Indore City", "Jabalpur City", "Gwalior City", "Ujjain City", 
        "Sagar City", "Rewa City", "Satna City", "Ratlam City", "Dewas City", "Khandwa City", 
        "Burhanpur City", "Chhindwara City", "Mandsaur City", "Morena City", "Vidisha City", 
        "Hoshangabad City", "Betul City", "Damoh City", "Katni City", "Shivpuri City", 
        "Neemuch City", "Chhatarpur City", "Pithampur City", "Sehore City", "Khargone City", 
        "Itarsi City", "Seoni City", "Balaghat City", "Ashoknagar City", "Tikamgarh City", 
        "Shahdol City", "Singrauli City", "Guna City", "Barwani City", "Harda City", 
        "Mandla City", "Dindori City", "Sidhi City", "Umaria City", "Narsinghpur City", 
        "Raisen City", "Dhar City", "Alirajpur City", "Jhabua City", "Shajapur City", 
        "Rajgarh City", "Sheopur City", "Anuppur City", "Agar City", "Sendhwa City", 
        "Pandhurna City", "Waraseoni City", "Pipariya City", "Sarni City", "Sohagpur City", 
        "Multai City", "Amla City", "Barwaha City", "Sanawad City", "Mandideep City", 
        "Biaora City", "Gadarwara City", "Kukshi City", "Manawar City", "Maheshwar City", 
        "Omkareshwar City", "Nagda City", "Tarana City", "Susner City", "Nalkheda City", 
        "Badnagar City", "Khachrod City", "Jaora City", "Mhow City", "Dr. Ambedkar Nagar City", 
        "Depalpur City", "Khilchipur City", "Sarangpur City", "Ashta City", "Ichhawar City", 
        "Nasrullaganj City", "Budhni City", "Rehti City", "Shahpur City", "Badi City", 
        "Kurwai City", "Lateri City", "Sironj City", "Shamgarh City", "Pachore City", 
        "Bhanpura City"
      ]
    },
    {
      state: "Maharashtra",
      citiesAndTowns: [
        "Mumbai", "Bombay", "Pune", "Poona", "Nagpur", "Nashik", "Nasik", "Aurangabad",
        "Solapur", "Thane", "Kolhapur", "Amravati", "Akola", "Jalgaon", "Latur", "Dhule",
        "Ahmednagar", "Sangli", "Satara", "Chandrapur", "Nanded", "Parbhani", "Malegaon",
        "Jalna", "Bhusawal", "Ichalkaranji", "Miraj", "Beed", "Gondia", "Wardha", "Yavatmal",
        "Barshi", "Pandharpur", "Khamgaon", "Buldhana", "Washim", "Hinganghat", "Osmanabad",
        "Karad", "Ratnagiri", "Chiplun", "Dahanu", "Palghar", "Virar", "Vasai", "Bhiwandi",
        "Kalyan", "Ulhasnagar", "Ambarnath", "Badlapur", "Panvel", "Navi Mumbai", "Khopoli",
        "Lonavala", "Khandala", "Matheran", "Mahad", "Pen", "Alibag", "Murud", "Shirdi",
        "Shirpur", "Chalisgaon", "Kopargaon", "Sangamner", "Manmad", "Yeola", "Sillod",
        "Kannad", "Vaijapur", "Paithan", "Gangapur", "Phaltan", "Wai", "Mahabaleshwar",
        "Panchgani", "Bhor", "Jejuri", "Saswad", "Purandar", "Shrigonda", "Karjat",
        "Murbad", "Shahapur", "Wada", "Junnar", "Narayangaon", "Maval", "Talegaon Dabhade",
        "Chakan", "Rajgurunagar", "Manchar", "Shirur", "Alandi", "Dehu", "Pimpri-Chinchwad",
        "Mumbai City", "Pune City", "Nagpur City", "Nashik City", "Aurangabad City", 
        "Solapur City", "Thane City", "Kolhapur City", "Amravati City", "Akola City", 
        "Jalgaon City", "Latur City", "Dhule City", "Ahmednagar City", "Sangli City", 
        "Satara City", "Chandrapur City", "Nanded City", "Parbhani City", "Malegaon City", 
        "Jalna City", "Bhusawal City", "Ichalkaranji City", "Miraj City", "Beed City", 
        "Gondia City", "Wardha City", "Yavatmal City", "Barshi City", "Pandharpur City", 
        "Khamgaon City", "Buldhana City", "Washim City", "Hinganghat City", "Osmanabad City", 
        "Karad City", "Ratnagiri City", "Chiplun City", "Dahanu City", "Palghar City", 
        "Virar City", "Vasai City", "Bhiwandi City", "Kalyan City", "Ulhasnagar City", 
        "Ambarnath City", "Badlapur City", "Panvel City", "Navi Mumbai City", "Khopoli City", 
        "Lonavala City", "Khandala City", "Matheran City", "Mahad City", "Pen City", 
        "Alibag City", "Murud City", "Shirdi City", "Shirpur City", "Chalisgaon City", 
        "Kopargaon City", "Sangamner City", "Manmad City", "Yeola City", "Sillod City", 
        "Kannad City", "Vaijapur City", "Paithan City", "Gangapur City", "Phaltan City", 
        "Wai City", "Mahabaleshwar City", "Panchgani City", "Bhor City", "Jejuri City", 
        "Saswad City", "Purandar City", "Shrigonda City", "Karjat City", "Murbad City", 
        "Shahapur City", "Wada City", "Junnar City", "Narayangaon City", "Maval City", 
        "Talegaon Dabhade City", "Chakan City", "Rajgurunagar City", "Manchar City", 
        "Shirur City", "Alandi City", "Dehu City", "Pimpri-Chinchwad City"
      ]
    },
    {
      state: "Manipur",
      citiesAndTowns: [
        "Imphal", "Thoubal", "Bishnupur", "Churachandpur", "Ukhrul", "Senapati", "Tamenglong",
        "Kakching", "Jiribam", "Moreh", "Kangpokpi", "Nambol", "Moirang", "Mayang Imphal",
        "Lilong", "Wangjing", "Yairipok", "Andro", "Oinam", "Lamshang", "Sekmai", "Lamlai",
        "Heirok", "Kumbi", "Saidu", "Sangaiprou", "Ningthoukhong", "Khangabok", "Sikhong Sekmai",
        "Porompat", "Keirao Bitra", "Kshetrigao", "Langthabal", "Naoriya Pakhanglakpa",
        "Wangoi", "Kakching Khunou", "Sugnu", "Chandel", "Tengnoupal", "Kamjong", "Mach",
        "Phungyar", "Kasom Khullen", "Tamei", "Nungba", "Haochong", "Khoupum", "Longmai",
        "Tousem", "Parbung", "Jirighat", "Lakhipur", "Henglep", "Saikul", "Saitu", "Pherzawl",
        "Tipaimukh", "Thanlon", "Henglep", "Lamka", "Singngat", "Jessami", "Mao", "Tadubi",
        "Paomata", "Purul", "Willong", "Pfutsero"
      ]
    },
    {
      state: "Meghalaya",
      citiesAndTowns: [
        "Shillong", "Tura", "Jowai", "Nongstoin", "Williamnagar", "Baghmara", "Nongpoh",
        "Mairang", "Resubelpara", "Mawngap", "Sohra", "Cherrapunji", "Mawkyrwat", "Khliehriat",
        "Pynursla", "Mawlai", "Sohiong", "Laitumkhrah", "Madanriting", "Umiam", "Umpling",
        "Nongthymmai", "Lawsohtun", "Mawpat", "Nongmynsong", "Laban", "Malki", "Upper Shillong",
        "Jaintia Hills", "Dawki", "Amlarem", "Lad Rymbai", "Sutnga", "Rymbai", "Bhoirymbong",
        "Umsning", "Mawryngkneng", "Smit", "Thadlaskein", "Mawsynram", "Jakrem", "Ranikor",
        "Pynthorumkhrah", "Shella", "Nartiang", "Jowai West", "Shangpung", "Raliang",
        "Mawthadraishan", "Markasa", "Nongtalang", "Rongram", "Dadenggre", "Tikrikilla",
        "Phulbari", "Selsella", "Rongjeng", "Songsak", "Samanda", "Bajengdoba", "Dambo Rongjeng"
      ]
    },
    {
      state: "Mizoram",
      citiesAndTowns: [
        "Aizawl", "Lunglei", "Saiha", "Champhai", "Kolasib", "Serchhip", "Lawngtlai", "Mamit",
        "Hnahthial", "Saitual", "Khawzawl", "Vairengte", "Bairabi", "North Vanlaiphai",
        "Thenzawl", "Tlabung", "Zawlnuam", "Sairang", "Lengpui", "Darlawng", "Chawngte",
        "Biate", "Khawbung", "Ngopa", "Hnahlan", "Thingsulthliah", "Sangau", "Tuipang",
        "West Phaileng", "Kawnpui", "Bilkhawthlir", "Bungtlang", "Lungsen", "Phullen",
        "Vangchhia", "Reiek", "Zobawk", "Darlawn", "Phuaibuang", "Sialsuk", "Mualthuam",
        "Thingdawl", "Hnahva", "Khuangleng", "Vawmbuk", "Chhiahtlang", "Tualbung",
        "Serkawn", "Buarpui", "Pangzawl", "Ratu", "Tlangnuam", "Zemabawk", "Bawngkawn",
        "Chhingchhip", "Khawhai", "Lungdai", "Mimbung", "Phuldungsei"
      ]
    },
    {
      state: "Nagaland",
      citiesAndTowns: [
        "Kohima", "Dimapur", "Mokokchung", "Tuensang", "Wokha", "Zunheboto", "Mon", "Phek",
        "Peren", "Longleng", "Kiphire", "Chumukedima", "Tseminyu", "Pfutsero", "Chozuba",
        "Meluri", "Shamator", "Noklak", "Bhandari", "Aghunato", "Atoizu", "Suruhoto",
        "Mangkolemba", "Tuli", "Changtongya", "Longkhim", "Tob", "Naganimora",
        "Jalukie", "Tening", "Medziphema", "Niuland", "Akuluto", "Satakha", "Pungro",
        "Chessore", "Thonoknyu", "Tobu", "Anaki", "Noksen", "Tamlu", "Longching",
        "Yingkiong", "Naginimora", "Merangkong", "Alongkima", "Kubolong", "Mopungchuket",
        "Chare", "Chuchuyimlang", "Impur", "Ungma", "Nungthem", "Zhadima", "Viswema",
        "Jakhama", "Khuzama", "Kigwema", "Pughoboto", "Ghathashi", "Rengma"
      ]
    },
    {
      state: "Odisha",
      citiesAndTowns: [
        "Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Brahmapur", "Sambalpur", "Puri",
        "Balasore", "Baripada", "Jharsuguda", "Jeypore", "Bhadrak", "Angul", "Dhenkanal",
        "Paradip", "Keonjhar", "Sunabeda", "Koraput", "Rayagada", "Balangir", "Bargarh",
        "Phulbani", "Kendrapara", "Jagatsinghpur", "Jajpur", "Nabarangpur", "Titlagarh",
        "Sundargarh", "Gunupur", "Malkangiri", "Soro", "Chatrapur", "Athmallik", "Banki",
        "Biramitrapur", "Boudh", "Choudwar", "Deogarh", "Dhamnagar", "Hinjilicut", "Kantabanji",
        "Khariar", "Khordha", "Nayagarh", "Nuapada", "Padampur", "Parlakhemundi", "Patnagarh",
        "Polasara", "Rairangpur", "Rajgangpur", "Subarnapur", "Sonepur", "Talcher", "Tarbha",
        "Umerkote", "Anandapur", "Asika", "Athagarh", "Balugaon", "Banapur", "Barbil",
        "Basudebpur", "Bellaguntha", "Bhanjanagar", "Binika", "Borigumma", "Buguda",
        "Chikiti", "Digapahandi", "Gopalpur", "Gudari", "Jaraka", "Jaleswar", "Kamakhyanagar",
        "Kashinagar", "Khalikote", "Kodala", "Kotpad", "Kuchinda", "Nimapara", "Pipili",
        "Purusottampur", "Rambha", "Sheragada", "Sorada", "Tangi", "Udala"
      ]
    },
    {
      state: "Punjab",
      citiesAndTowns: [
        "Amritsar", "Ludhiana", "Jalandhar", "Patiala", "Bathinda", "Mohali", "Pathankot",
        "Hoshiarpur", "Gurdaspur", "Moga", "Firozpur", "Phagwara", "Kapurthala", "Sangrur",
        "Muktsar", "Barnala", "Faridkot", "Malerkotla", "Abohar", "Fazilka", "Khanna",
        "Rupnagar", "Ropar", "Nawanshahr", "Tarn Taran", " Batala", "Rajpura", "Mansa",
        "Anandpur Sahib", "Nangal", "Zira", "Kotkapura", "Sunam", "Dhuri", "Samrala",
        "Budhlada", "Dasuya", "Dera Bassi", "Dinanagar", "Doraha", "Garhshankar", "Giddarbaha",
        "Gobindgarh", "Jagraon", "Malout", "Mandi Gobindgarh", "Morinda", "Mukerian",
        "Nakodar", "Nabha", "Patti", "Phillaur", "Qadian", "Raikot", "Rampura Phul",
        "Sanaur", "Sultanpur Lodhi", "Talwandi Bhai", "Tapa", "Zirakpur", "Ajnala",
        "Balachaur", "Banga", "Bhawanigarh", "Bhikhi", "Dhariwal", "Fatehgarh Churian",
        "Gardhiwala", "Hariana", "Jaitu", "Kalanaur", "Khamanon", "Lehra Gaga", "Machhiwara",
        "Majitha", "Moonak", "Payal", "Raman", "Sahnewal", "Samana", "Sardulgarh", "Urmar Tanda"
      ]
    },
    {
      state: "Rajasthan",
      citiesAndTowns: [
        "Jaipur", "Jodhpur", "Udaipur", "Kota", "Bikaner", "Ajmer", "Alwar", "Bhilwara",
        "Sikar", "Pali", "Sri Ganganagar", "Hanumangarh", "Bharatpur", "Dholpur", "Churu",
        "Jhunjhunu", "Nagaur", "Barmer", "Jaisalmer", "Bundi", "Tonk", "Sawai Madhopur",
        "Chittorgarh", "Dausa", "Rajsamand", "Baran", "Jhalawar", "Beawar", "Makrana",
        "Sirohi", "Abu Road", "Balotra", "Fatehpur", "Lachhmangarh", "Ratangarh", "Sujangarh",
        "Neem Ka Thana", "Nohar", "Suratgarh", "Anupgarh", "Bhadra", "Chirawa", "Khetri",
        "Mandawa", "Nawalgarh", "Pilani", "Banswara", "Pratapgarh", "Dungarpur", "Kushalgarh",
        "Bayana", "Deeg", "Kaman", "Nagar", "Bari", "Bandikui", "Gangapur City", "Hindaun",
        "Karauli", "Lalsot", "Phalodi", "Piparcity", "Pokaran", "Ramganj Mandi", "Rawatbhata",
        "Sadri", "Salumbar", "Sangaria", "Sardarshahar", "Shahpura", "Sojat", "Taranagar",
        "Tijara", "Bhinmal", "Jalore", "Raniwara", "Sanchore", "Bagru", "Chaksu", "Jobner",
        "Kotputli", "Nasirabad", "Nimbahera", "Pushkar", "Raisinghnagar", "Reengus",
        "Samdari", "Sheoganj", "Todaraisingh", "Uniara", "Vijainagar"
      ]
    },
    {
      state: "Sikkim",
      citiesAndTowns: [
        "Gangtok", "Namchi", "Gyalshing", "Mangan", "Ravangla", "Jorethang", "Singtam",
        "Rangpo", "Pelling", "Naya Bazar", "Melli", "Soreng", "Yuksom", "Rhenock", "Rongli",
        "Pakyong", "Chungthang", "Lachen", "Lachung", "Dentam", "Kaluk", "Temi", "Tarku",
        "Yangang", "Damthang", "Khamdong", "Majitar", "Ranipool", "Reshi", "Sumbuk",
        "Namthang", "Kewzing", "Lingmoo", "Lingdong", "Barfung", "Assangthang", "Bermiok",
        "Chakung", "Dikchu", "Hee Bazar", "Kabi", "Lingtam", "Makha", "Martam", "Namprikdang",
        "Phodong", "Ralong", "Rolep", "Samdong", "Sang", "Sikkip", "Tadong", "Tashiding",
        "Tingmoo", "Tingvong", "Upper Tadong", "Yangthang"
      ]
    },
    {
      state: "Tamil Nadu",
      citiesAndTowns: [
        "Chennai", "Madras", "Coimbatore", "Madurai", "Tiruchirappalli", "Trichy", "Salem",
        "Erode", "Vellore", "Tirunelveli", "Thoothukudi", "Tuticorin", "Dindigul", "Thanjavur",
        "Nagercoil", "Kanyakumari", "Hosur", "Kanchipuram", "Karur", "Namakkal", "Pudukkottai",
        "Sivakasi", "Tiruppur", "Cuddalore", "Kumbakonam", "Rajapalayam", "Pollachi",
        "Nagapattinam", "Ooty", "Udhagamandalam", "Krishnagiri", "Dharmapuri", "Arakkonam",
        "Ariyalur", "Attur", "Bhavani", "Chengalpattu", "Chidambaram", "Coonoor", "Covai",
        "Gobichettipalayam", "Gudiyatham", "Kallakurichi", "Karaikudi", "Katpadi", "Kodaikanal",
        "Kotagiri", "Kovilpatti", "Mayiladuthurai", "Mettupalayam", "Mettur", "Palani",
        "Palladam", "Papanasam", "Paramakudi", "Pattukkottai", "Perambalur", "Poonamallee",
        "Ramanathapuram", "Ranipet", "Sathyamangalam", "Sivaganga", "Tenkasi", "Theni",
        "Tindivanam", "Tiruvannamalai", "Uthangarai", "Valparai", "Vaniyambadi", "Vedaranyam",
        "Villupuram", "Virudhachalam", "Virudhunagar", "Ambur", "Arani", "Aruppukkottai",
        "Denkanikottai", "Devakottai", "Dharapuram", "Gingee", "Jayankondam", "Manapparai",
        "Melur", "Oddanchatram", "Periyakulam", "Sankarankovil", "Sholinghur", "Sirkazhi",
        "Tharangambadi", "Tranquebar", "Tiruttani", "Tiruvallur", "Udumalaipettai"
      ]
    },
    {
      state: "Telangana",
      citiesAndTowns: [
        "Hyderabad", "Warangal", "Orugallu", "Nizamabad", "Karimnagar", "Khammam", "Secunderabad",
        "Mahbubnagar", "Adilabad", "Suryapet", "Nalgonda", "Siddipet", "Miryalaguda",
        "Jagtial", "Mancherial", "Sangareddy", "Kothagudem", "Bhongir", "Kamareddy", "Wanaparthy",
        "Vikarabad", "Jangaon", "Medak", "Gadwal", "Peddapalli", "Tandur", "Kodad", "Armoor",
        "Huzurnagar", "Devarakonda", "Yellandu", "Bellampalli", "Banswada", "Bodhan",
        "Dubbak", "Ibrahimpatnam", "Kagaznagar", "Koratla", "Madhira", "Metpally", "Naspur",
        "Nirmal", "Palwancha", "Sathupalli", "Shadnagar", "Sircilla", "Zaheerabad", "Asifabad",
        "Chennur", "Chincholi", "Dornakal", "Ghanpur", "Husnabad", "Jammikunta", "Luxettipet",
        "Mandamarri", "Mulug", "Narayanpet", "Patancheru", "Ramagundam", "Shamshabad",
        "Thorrur", "Vemulawada", "Yellareddy", "Bhadrachalam", "Cherial", "Chityal",
        "Eturunagaram", "Ghatkesar", "Golkonda", "Haliya", "Jainath", "Kesamudram",
        "Khanapur", "Kondapur", "Kosgi", "Kyathampalle", "Laxettipet", "Mahabubabad",
        "Manuguru", "Marripeda", "Narsampet", "Parkal", "Pedda Amberpet", "Shankarpalli",
        "Thungathurthi", "Wyra"
      ]
    },
    {
      state: "Tripura",
      citiesAndTowns: [
        "Agartala", "Udaipur", "Dharmanagar", "Kailashahar", "Ambassa", "Belonia", "Khowai",
        "Sabroom", "Sonamura", "Teliamura", "Amarpur", "Ranirbazar", "Kumarghat", "Bishalgarh",
        "Melaghar", "Santirbazar", "Kamalpur", "Jirania", "Mohanpur", "Fatikroy", "Kanchanpur",
        "Manu", "Pecharthal", "Panisagar", "Chailengta", "Gandacherra", "Salema", "Tulashikhar",
        "Bagbassa", "Bampur", "Barpathari", "Bishramganj", "Boxanagar", "Chandipur",
        "Charipara", "Damcherra", "Dasda", "Durganagar", "Gakulnagar", "Garjee", "Hrishyamukh",
        "Jamjuri", "Jampui Hill", "Kadamtala", "Kalachhara", "Khedacherra", "Killa",
        "Laljuri", "Machmara", "Manubazar", "Matabari", "Mohanbhog", "Nabinagar", "Nadiapur",
        "Natunbazar", "Nutanbazar", "Pencharthal", "Radhanagar", "Rajnagar", "Rangamati",
        "Ratannagar", "Satchand", "Sidhai", "Simna", "Srinagar", "Surma", "Takmacherra"
      ]
    },
    {
      state: "Uttar Pradesh",
      citiesAndTowns: [
        "Lucknow", "Kanpur", "Cawnpore", "Agra", "Varanasi", "Benares", "Allahabad", "Prayagraj",
        "Meerut", "Ghaziabad", "Noida", "Greater Noida", "Gorakhpur", "Jhansi", "Aligarh",
        "Bareilly", "Moradabad", "Saharanpur", "Muzaffarnagar", "Mathura", "Firozabad",
        "Rampur", "Shahjahanpur", "Farrukhabad", "Hapur", "Etawah", "Mirzapur", "Bulandshahr",
        "Sambhal", "Amroha", "Hardoi", "Fatehpur", "Raebareli", "Sitapur", "Bahraich",
        "Modinagar", "Unnao", "Jaunpur", "Lakhimpur", "Hathras", "Banda", "Pilibhit",
        "Barabanki", "Khurja", "Gonda", "Mainpuri", "Ballia", "Azamgarh", "Sultanpur",
        "Bijnor", "Basti", "Chandausi", "Akbarpur", "Tanda", "Shikohabad", "Shamli",
        "Mawana", "Kasganj", "Mughalsarai", "Chandpur", "Nagina", "Thakurdwara", "Budaun",
        "Deoria", "Orai", "Renukoot", "Kannauj", "Ghazipur", "Chitrakoot", "Balrampur",
        "Auraiya", "Lalitpur", "Etah", "Robertsganj", "Ujhani", "Gangaghat", "Obra",
        "Pukhrayan", "Kairana", "Najibabad", "Chhibramau", "Dadri", "Pilkhuwa", "Dasna",
        "Khair", "Jewar", "Tilhar", "Atrauli", "Jalesar", "Sikandrabad", "Anupshahr",
        "Bhadohi", "Gyanpur", "Hamirpur", "Mahoba"
      ]
    },
    {
      state: "Uttarakhand",
      citiesAndTowns: [
        "Dehradun", "Haridwar", "Rishikesh", "Nainital", "Mussoorie", "Roorkee", "Haldwani",
        "Rudrapur", "Kashipur", "Pithoragarh", "Almora", "Bageshwar", "Chamoli", "Uttarkashi",
        "Tehri", "Pauri", "Kotdwar", "Ramnagar", "Khatima", "Tanakpur", "Jaspur", "Bazpur",
        "Kichha", "Sitarganj", "Laksar", "Manglaur", "Jhabrera", "Landhaura", "Doiwala",
        "Vikasnagar", "Herbertpur", "Narendranagar", "Chamba", "Devprayag", "Gopeshwar",
        "Joshimath", "Bhowali", "Ranikhet", "Mukteshwar", "Champawat", "Lohaghat", "Dharchula",
        "Didihat", "Berinag", "Gangolihat", "Tharali", "Karnaprayag", "Rudraprayag",
        "Srinagar", "Gauchar", "Lansdowne", "Gairsain", "Bhikiyasain", "Chaukhutia",
        "Dwarahat", "Salt", "Someshwar", "Kapkot", "Thal", "Munsiari", "Askot", "Kanda",
        "Dhumakot", "Satpuli", "Dhanaulti", "Chakrata", "Purola", "Mori", "Barkot",
        "Naugaon", "Rajgarhi", "Tuini", "Kalsi", "Bhagwanpur", "Bahadarabad", "Laldhang",
        "Luxar", "Pirankaliyar", "Shyampur", "Behat"
      ]
    },
    {
      state: "West Bengal",
      citiesAndTowns: [
        "Kolkata", "Calcutta", "Howrah", "Durgapur", "Siliguri", "Asansol", "Darjeeling",
        "Malda", "Bardhaman", "Burdwan", "Kharagpur", "Haldia", "Jalpaiguri", "Cooch Behar",
        "Bankura", "Purulia", "Midnapore", "Medinipur", "Raiganj", "Balurghat", "Krishnanagar",
        "Berhampore", "Bahadurpur", "Suri", "Bolpur", "Ranaghat", "Barasat", "Basirhat",
        "Bongaon", "Diamond Harbour", "Tamluk", "Contai", "Kanthi", "Alipurduar", "Falta",
        "Chinsurah", "Hooghly", "Serampore", "Arambagh", "Chandannagar", "Barrackpore",
        "Titagarh", "Kalyani", "Naihati", "Bhatpara", "Dum Dum", "Bidhannagar", "Salt Lake",
        "Habra", "Ashoknagar", "Kanchrapara", "Halisahar", "Bansberia", "Rishra", "Konnagar",
        "Uttarpara", "Bhadreswar", "Budge Budge", "Pujali", "Baruipur", "Rajpur Sonarpur",
        "Jaynagar Majilpur", "Uluberia", "Bauria", "Kulti", "Raniganj", "Jamuria", "Sainthia",
        "Rampurhat", "Nalhati", "Islampur", "Kaliaganj", "Gangarampur", "Domkal", "Farakka",
        "Jangipur", "Dhulian", "Lalgola", "Murshidabad", "Jiaganj", "Raghunathganj",
        "Egra", "Ghatal", "Jhargram", "Panskura", "Dantan", "Mekliganj", "Mathabhanga",
        "Tufanganj", "Dinhata", "Sitai", "Gosaba", "Kakdwip", "Namkhana", "Patharpratima",
        "Sagar Island"
      ]
    }
  ];
  
  

// Initialize data structures from the city data
const initialize = () => {
  // Make sure we have the data in the expected format
  const cityData = Array.isArray(statesOfIndiaPart1) ? statesOfIndiaPart1 : 
                  (statesOfIndiaPart1.statesOfIndiaPart1 || []);
                  
  if (!cityData || cityData.length === 0) {
    console.error("No city data found. City detection will not work.");
    return false;
  }
  
  console.log(`Initializing city detection with ${cityData.length} states...`);
  
  // Process each state and its cities
  cityData.forEach(stateData => {
    const state = stateData.state;
    stateMap.set(state.toLowerCase(), state); // Map state name to proper case
    
    if (!stateData.citiesAndTowns || !Array.isArray(stateData.citiesAndTowns)) {
      console.warn(`No cities found for state: ${state}`);
      return;
    }
    
    stateData.citiesAndTowns.forEach(city => {
      // Normalize city name (lowercase, remove "City" suffix)
      const normalizedCity = city.replace(/ City$/, '').toLowerCase();
      
      // Store in direct lookup map
      cityIndex.set(normalizedCity, {
        originalName: city.replace(/ City$/, ''),
        state
      });
      
      // Add to list for fuzzy search
      cityNameList.push({
        name: normalizedCity,
        originalName: city.replace(/ City$/, ''),
        state
      });
      
      // Also add any known variants of this city
      const cityLower = normalizedCity.toLowerCase();
      Object.entries(cityVariants).forEach(([canonical, variants]) => {
        if (cityLower === canonical.toLowerCase()) {
          variants.forEach(variant => {
            cityIndex.set(variant.toLowerCase(), {
              originalName: city.replace(/ City$/, ''),
              state,
              variant: true
            });
          });
        }
      });
    });
  });
  
  console.log(`City detection initialized with ${cityIndex.size} city names and variants`);
  return true;
};

// Find city by exact name match
const findExactCity = (name) => {
  if (!name) return null;
  const normalizedName = name.toLowerCase().trim();
  return cityIndex.get(normalizedName) || null;
};

// Find city by substring match (city name appears within a text)
const findCityInText = (text) => {
  if (!text || typeof text !== 'string') return null;
  const textLower = text.toLowerCase();
  
  // First check for exact words
  const words = textLower.split(/[\s,.!?;\-:()[\]{}'"]+/);
  
  // Try individual words
  for (const word of words) {
    if (word.length < 3) continue; // Skip very short words
    const cityInfo = findExactCity(word);
    if (cityInfo) return cityInfo;
  }
  
  // Try word pairs (for multi-word city names)
  for (let i = 0; i < words.length - 1; i++) {
    const pair = `${words[i]} ${words[i + 1]}`;
    const cityInfo = findExactCity(pair);
    if (cityInfo) return cityInfo;
  }
  
  // Try word triplets (for city names with 3 words)
  for (let i = 0; i < words.length - 2; i++) {
    const triplet = `${words[i]} ${words[i + 1]} ${words[i + 2]}`;
    const cityInfo = findExactCity(triplet);
    if (cityInfo) return cityInfo;
  }
  
  // Next, check for common city variants
  for (const [canonical, variants] of Object.entries(cityVariants)) {
    // Check if the canonical name is in the text
    if (textLower.includes(canonical)) {
      // Look up the canonical city
      const cityData = [...cityIndex.entries()]
        .find(([key, value]) => key === canonical);
      
      if (cityData) {
        return cityData[1];
      }
    }
    
    // Check if any variant is in the text
    for (const variant of variants) {
      if (textLower.includes(variant)) {
        // Look up using the canonical name
        const cityData = [...cityIndex.entries()]
          .find(([key, value]) => key === canonical);
        
        if (cityData) {
          return cityData[1];
        }
      }
    }
  }
  
  // If still no match, check if any city name is included in the text as a substring
  for (const [cityName, cityInfo] of cityIndex.entries()) {
    // Only check cities with names 5+ characters to avoid false matches
    if (cityName.length >= 5 && textLower.includes(cityName)) {
      return cityInfo;
    }
  }
  
  return null;
};

// Main detection function
const detectLocation = (text) => {
  if (!text) return null;
  
  // Special case for Belagavi/Belgaum which seems problematic
  const textLower = text.toLowerCase();
  if (textLower.includes('belagavi') || textLower.includes('belgaum') || 
      textLower.includes('belgavi') || textLower.includes('belgam')) {
    return {
      city: "Belagavi",
      state: "Karnataka"
    };
  }
  
  const cityInfo = findCityInText(text);
  if (cityInfo) {
    return {
      city: cityInfo.originalName,
      state: cityInfo.state
    };
  }
  
  return null;
};

// Initialize the data structures
const isInitialized = initialize();

module.exports = {
  detectLocation,
  findExactCity,
  findCityInText,
  cityNameList,
  isInitialized
};
