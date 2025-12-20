import os

class DataLoggerCSV:
    def __init__(self, filename):
        self.filename = filename
        # use append mode so we dont lose previous sessions
        file_exists = os.path.exists(filename) and os.path.getsize(filename) > 0
        self.file = open(filename, 'a')
        if not file_exists:
            self.file.write("time,on,off,diff\n")
            self.file.flush()
    
    def log(self, data):
        self.file.write(f"{data['time']},{data['on']},{data['off']},{data['diff']}\n")
        # flush to ensure data is written to disk even if killed
        self.file.flush()
    
    def close(self):
        self.file.close()