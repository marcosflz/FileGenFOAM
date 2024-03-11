from tkinter import filedialog, messagebox
from tkinter import  ttk

import tkinter as tk
import configparser
import sourceFOAM



def get_bound_names(file_path):
    boundary_names = []
    with open(file_path, 'r') as file:
        boundary_section = False
        for line in file:
            line = line.rstrip()
            if line.startswith("FoamFile") or line.startswith("//"):
                continue
            if line == "(":  
                boundary_section = True
                continue
            if line == ")":  
                boundary_section = False
                continue
            if boundary_section and not ("{" in line or "}" in line or line.endswith(";")):
                boundary_name = line.split()[0]
                boundary_names.append(boundary_name)
    return boundary_names


def gen_files(var,varDim,varTyp,boundaries,sourceFunc):
    if var not in varDim:
        raise ValueError(f"La variable '{var}' no está definida en varDim")
    content = sourceFunc(var, varDim, varTyp, boundaries)
    return content


def textBox_Var(var):
    global folder0_files
    try:
        clearText()
        textBox.insert(tk.END,getattr(folder0_files, var))
    except Exception:
        return messagebox.showinfo("Warning", "No boundary file selected.")
    

def preserve_case(option):
    return option

def clearText():
    textBox.delete('1.0', tk.END)

def deleteFile():
    clearText()
    global folder0_files
    folder0_files = None

def importFile():
    global folder0_files
    file_path = filedialog.askopenfilename()
    def inner():
        if file_path:
            with open(file_path, 'r') as file:
                new_elements = file.readlines()
                textBox.delete('1.0', tk.END)
                textBox.insert(tk.END, "".join(new_elements))
    boundaries = get_bound_names(file_path)
    folder0_files = write0Files(varDim, varTyp, boundaries, sourceFOAM.folder0)
    return inner()

def exportFile():
    content = textBox.get("1.0", tk.END)
    lines = content.split('\n')
    for line in lines:
        if 'object' in line:
            export_name = str(line.split()[-1].strip(";"))
            with open(export_name, 'w') as file:
                file.write(content)

def update_button_text():
    selected_folders = magnitudes_list.get()     
    writeButton.config(text='Write ' + selected_folders) 

class write0Files:
    def __init__(self, varDim, varTyp,boundary, sourceFunc):
        self.variables = varDim.keys()
        for var in self.variables:
            setattr(self, var, gen_files(var, varDim, varTyp, boundary, sourceFunc))


folder0_files = None

config = configparser.ConfigParser()
config.optionxform = preserve_case
config.read('config.ini')

folder0_dim = config['folder_0_Dim']
folder0_typ = config['folder_0_Type']
varDim = {key: value for key, value in folder0_dim.items()}
varTyp = {key: value for key, value in folder0_typ.items()}


window = tk.Tk()
window.title("OpenFOAM File Generator")
window.resizable(False, False)  
h, w = 30,80

textBox = tk.Text(window, height=h, width=w)
textBox.grid(row=1, column=0, columnspan=4, padx=0, pady=0)

boundary_import_button = tk.Button(window, text="Select File", command=lambda:importFile())
boundary_import_button.grid(row=0, column=0, padx=5, pady=5, sticky="nwse")

magnitudes = list(list(varDim.keys()))
magnitudes_list = ttk.Combobox(window, values=magnitudes) 
magnitudes_list.set(magnitudes[0])  
magnitudes_list.grid(row=0, column=1, columnspan=2, sticky='nwse')  
magnitudes_list.bind("<<ComboboxSelected>>", lambda event: update_button_text())

writeButton = tk.Button(window, text="Write U", command=lambda:textBox_Var(magnitudes_list.get()))
writeButton.grid(row=0, column=3, padx=5, pady=5, sticky="nwse")

deleteFile_button = tk.Button(window, text="Delete File", command=lambda:deleteFile())
deleteFile_button.grid(row=2, column=0, padx=5, pady=5, sticky="nwse")

deleteFile_button = tk.Button(window, text="Clean Text Box", command=lambda:clearText())
deleteFile_button.grid(row=2, column=1, columnspan=2, padx=5, pady=5, sticky="nwse")

export_button = tk.Button(window, text="Export Text Box", command=lambda:exportFile())
export_button.grid(row=2, column=3, padx=5, pady=5, sticky="nwse")

window.mainloop()