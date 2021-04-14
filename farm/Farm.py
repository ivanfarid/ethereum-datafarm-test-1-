import requests
import time
import json
import glob
import re
from farm.helpers.Contract import Contract
from farm.helpers.ContractLoader import load_contracts, animation
from farm.helpers.EventHelper import from_hex

#
# Farm
# A farm instance is used to take an array of contracts to loop through it and execute a contract's function
# 
class Farm:
    def __init__(self, contracts, keyPath=".apikey/key.txt", aws_bucket=None, useBigQuery=False, canSwitch=False):
        self.contracts = contracts                 # Contracts objs.
        self.contract_length = len(contracts)      # Number of contracts
        self.waitingMonitor = 0                    # Helper to slow down scraping
        with open(keyPath) as k:                   # Load API KEY
            self.KEY = str(k.read().strip())
        self.latestBlock = self.get_latest_block() # Set latest block
        self.aws_bucket = aws_bucket               # AWS Bucket name
       
        self.lag = 4000                            # Block delay to not risk invalid blocks
        self.useBigQuery = useBigQuery             # BigQuery Upload
        self.canSwitch = canSwitch                 # Specify if the contracts.csv file can be switched
        self.currentContractPath = self.contracts[0].path
        print("\n")
        animation("Initiating Farm Instance with {} Contracts/Methods".format(len(contracts)))
                
    
    # Main function
    def start_farming(self):
        # Endless == True if end.txt == False => allows to safely end the program at the beginning of an iteration
        endless = True
        self.log_header()
        while(endless):
            endless = self.safe_end()
            # Slow down program if the latest block is reached for every token
            self.adjust_speed()
            # Update latestBlock
            self.latestBlock = self.get_latest_block()
            
            if self.canSwitch:
                print("Switch contract.csv config file")
                self.currentConfigPath = self.get_next_file()
                self.contracts=[]
                start = True
            else:
                self.currentConfigPath = self.contracts[0].path
                start=False
            # Load or remove new contracts
            self.contracts = load_contracts(
                                            self.contracts, 
                                            start, 
                                            config_location=self.currentConfigPath, 
                                            aws_bucket=self.aws_bucket
                                           )
            
            # Loop over the list of contracts
            for i in self.contracts: 
                # If latestBlock is reached => wait
                if self.not_wait(i):
                    # API request
                    query = i.query_API(self.KEY)
                    # Try to increase the chunksize
                    if i.chunksize_could_be_larger() and i.chunksizeLock == False:
                        i.increase_chunksize()
                    if query:
                        # Prepare raw request for further processing
                        chunk = i.mine(query, i.method.id)
                        print(i.log_to_console(chunk))
                        result = i.DailyResults.enrich_daily_results_with_day_of_month(chunk)
                        
                        # Try to safe results
                        i.DailyResults.try_to_save_day(result, i, self.aws_bucket, self.useBigQuery)
                        
                else:
                    print("Waiting for {}".format(i.name))
                    if i.shouldWait == False:
                        i.shouldWait = True
                        self.waitingMonitor += 1
                    self.wait(i)
    
    # Wait some time if every contract reached the latest block
    def adjust_speed(self):
        if self.contract_length == self.waitingMonitor:
            self.activate_contract_change()
            time.sleep(10)
    
    # Activate the looping over the contracts.csv files
    def activate_contract_change(self):
        self.canSwitch = True
    
    # Get next contracts.csv configuration file
    def get_next_file(self):
        contractPaths = glob.glob("../contracts*")
        if len(contractPaths) == 1:
            return self.currentContractPath
        currentIndex = contractPaths.index(self.currentContractPath)
        regexStr = "contracts({})?".format(currentIndex+1)
        if re.search(regexStr, i).group(1):
            return "contracts" + str(currentIndex+1)
        regexStr = "contracts({})?".format(currentIndex+2)
        if re.search(regexStr, i).group(1):
            return "contracts" + str(currentIndex+2)
        else:
            return "contracts"        
        
    # Get latest mined block from Etherscan
    def get_latest_block(self):
        q = 'https://api.etherscan.io/api?module=proxy&action=eth_blockNumber&apikey={}'
        try:
            return from_hex(json.loads(requests.get(q.format(self.KEY)).content)['result'])
        except:
            print("Except latest block")
            q = q.format(self.KEY)
            if "Bad Gateway" in str(q):
                print("Bad Gateway - latest Block")
                time.sleep(10)
                return self.latestBlock
            q = q.content
            q = requests.get(q)
            print(q)                
            q = json.loads(q)['result']
            lB = from_hex(q)
            return lB            
    
    # Wait if getting very close (self.lag) to the latestBlock
    def not_wait(self, contract):
        if contract.fromBlock + self.lag + contract.chunksize >= self.latestBlock:
            return False
        return True  
    
    # Wait and adapt/lock chunksize
    def wait(self, contract):
        if contract.chunksize > 1000:
                contract.chunksize = round(contract.chunksize/2)
        else:
            contract.chunksize = len(self.contracts)
            contract.chunksizeLock = True
        # If every contract reached the latest mined block then wait

    
    # Print status of the current instance, including its contracts 
    def status(self):
        string = ""
        for s in self.contracts:
            string += s.__repr__() + "\n"
        print("Farm instance initiated with the following contracts\n\n{}".format(string))
        time.sleep(1)
        return self
    
    # Header of output
    def log_header(self):
        header = ("Timestamp", "Contract", "Current Chunk", "Chunk Timestamp", "Events", "Chsz", "Fc")
        log = "\033[4m{:^23}-{:^18}|{:^21}| {:^20}|{:^6}|{:^6}|{:^6}\033[0m".format(*header)
        print(log)
    
    # Check end.txt file if the program should stop
    def safe_end(self):
        try:
            with open("config/end.txt") as endfile:
                return False if endfile.read().strip() == "True" else True
        except:
            return True
