class DataLoggerCSV:
    def __init__(self, filename):
        self.filename = filename
        self.file = open(filename, 'w')
        self.file.write("time,on,off,diff\n")
    
    def log(self, data):
        self.file.write(f"{data['time']},{data['on']},{data['off']},{data['diff']}\n")
    
    def close(self):
        self.file.close()