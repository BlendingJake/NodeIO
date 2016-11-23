bl_info = {
    "name": "Material IO",
    "author": "Jacob Morris",
    "version": (2, 0),
    "blender": (2, 78, 0),
    "location": "Properties > Materials",
    "description": "Allows The Exporting And Importing Of Materials Via .bmat Files",
    "category": "Import-Export"
    }

import bpy
from bpy.props import StringProperty, EnumProperty, BoolProperty
from datetime import datetime
from time import tzname
import xml.etree.cElementTree as ET
import ast
import operator
from inspect import getmembers
from os import path, mkdir, listdir, walk, remove as remove_file, sep as os_file_sep
from shutil import copyfile, rmtree
from xml.dom.minidom import parse as pretty_parse
import zipfile
import string
from mathutils import *
import json


def make_tuple(data):
    out = [round(i, 4) for i in data]
    return tuple(out)


def serialize(name):  # serialize names
    f = ""
    for i in name:
        if i not in string.ascii_letters and i not in string.digits and i != "_":
            f += "_"
        else:
            f += i   
    return f


def collect_node_data(n: bpy.types.Node):
    ns, inputs, outputs, images = [], [], [], []
    is_group = True if n.type == "GROUP" else False

    if n.bl_idname != "NodeReroute":  # Reroute does have in and out, but does not know type until linked
        # inputs
        if n.type != "GROUP_INPUT":
            for j in range(len(n.inputs)):
                data = n.inputs[j]
                if data.type in ("RGBA", "RGB", "VECTOR"):
                    inputs.append(j)
                    inputs.append(make_tuple(data.default_value))
                elif data.type == "VALUE":
                    inputs.append(j)
                    inputs.append(data.default_value)
                elif n.type == "GROUP" and data.type == "SHADER":
                    inputs.append(j)
                    inputs.append("SHADER")
        else:
            temp = []
            for i in n.inputs:
                temp.append(i.bl_idname)
                temp.append(serialize(i.name))
            ns += ["group_input", temp]

        # outputs
        if n.type != "GROUP_OUTPUT":
            for j in range(len(n.outputs)):
                data = n.outputs[j]
                if data.type in ("RGBA", "RGB", "VECTOR"):
                    outputs.append(j)
                    outputs.append(make_tuple(data.default_value))
                elif data.type == "VALUE":
                    outputs.append(j)
                    outputs.append(data.default_value)
                elif n.type == "GROUP" and data.type == "SHADER":
                    outputs.append(j)
                    outputs.append("SHADER")
        else:
            temp = []
            for i in n.outputs:
                temp.append(i.bl_idname)
                temp.append(serialize(i.name))
            ns += ["group_output", temp]

    # list of default values to ignore for smaller file-size, or because not needed, also if property is read-only
    exclude_list = ['__doc__', '__module__', '__slots__', 'bl_description', 'bl_height_default', 'bl_height_max',
                    'bl_height_min', 'bl_icon', 'bl_rna', 'bl_static_type', 'bl_width_default', 'bl_width_min',
                    'bl_width_max', 'color_mapping', 'draw_buttons', 'draw_buttons_ext', 'image_user', 'input_template',
                    'inputs', 'internal_links', 'is_registered_node_type', 'bl_label', 'output_template', 'outputs',
                    'poll', 'poll_instance', 'rna_type', 'shading_compatibility', 'show_options', 'show_preview',
                    'show_texture', 'socket_value_update', 'texture_mapping', 'type', 'update', 'viewLocation',
                    'width_hidden', 'bl_idname', 'dimensions', 'isAnimationNode']
    exclude = {}  # for checking item membership, dict is faster then list
    for i in exclude_list:
        exclude[i] = i

    for method in getmembers(n):
        if method[0] not in exclude:
            t = method[1]
            val = eval("n.{}".format(method[0]))  # get value

            if isinstance(t, (Vector, Color, Euler, Quaternion)):  # TUPLE
                ns += [method[0], make_tuple(val)]
            elif isinstance(t, bpy.types.CurveMapping):  # CURVES
                curves = [make_tuple(n.mapping.black_level), make_tuple(n.mapping.white_level),
                          str(n.mapping.clip_max_x), str(n.mapping.clip_max_y), str(n.mapping.clip_min_x),
                          str(n.mapping.clip_min_y), str(n.mapping.use_clip)]

                for curve in n.mapping.curves:
                    points = [curve.extend]
                    for point in curve.points:
                        points.append([make_tuple(point.location), point.handle_type])
                    curves.append(points)
                ns += ["mapping", curves]
            elif isinstance(t, bpy.types.ColorRamp):  # COLOR RAMP
                els = []
                for j in n.color_ramp.elements:
                    cur_el = [j.position, make_tuple(j.color)]
                    els.append(cur_el)
                ns += ["color_ramp.color_mode", n.color_ramp.color_mode, "color_ramp.interpolation",
                       n.color_ramp.interpolation, "color_ramp.elements", els]
            elif isinstance(t, bpy.types.NodeTree):  # NODE TREE
                ns += ["node_tree.name", val.name]
            elif isinstance(t, bpy.types.Image) and n.image is not None:  # IMAGE
                ns += ["image", n.image.name]
                images.append([n.image.name, n.image.filepath])
            elif isinstance(t, bpy.types.ParticleSystem):  # PARTICLE SYSTEM - needs objects and particle system
                ns += [method[0], [n.object, val.name]]
            elif isinstance(t, str):  # STRING
                ns += [method[0], serialize(val)]
            elif isinstance(t, (int, float)):  # FlOAT, INTEGER
                ns += [method[0], val]
            elif isinstance(t, bpy.types.Node):  # FRAME NODE
                ns += [method[0], serialize(val.name)]

    return [{"inputs": inputs, "outputs": outputs, "node_specific": ns, "bl_idname": n.bl_idname}, is_group, images]


# recursive method that collects all nodes and if group node goes and collects its nodes
# data is added to data in [[nodes, links], [nodes, links]] group by group
def collect_nodes(nodes, links, images, names, name, data):
    m_n = []
    m_l = []
    
    for n in nodes:  # nodes
        out, is_group, im = collect_node_data(n)
        m_n.append(out)
        images.append(im)
        
        if is_group:
            collect_nodes(n.node_tree.nodes, n.node_tree.links, images, names, n.node_tree.name, data)    
        
    for l in links:  # links
        out = link_info(l)
        m_l.append(out)
        
    data.append([m_n, m_l])   
    names[name] = len(data) - 1 


def link_info(link):
    out = [serialize(link.from_node.name)]

    fr = link.from_socket.path_from_id()
    fr = fr.split(".")

    if len(fr) == 3:
        fr = fr[2]
    else:
        fr = fr[1]

    n1 = fr.index("[")
    n2 = fr.index("]")
    ind = int(fr[n1 + 1:n2])
    out.append(ind)
    out.append(serialize(link.to_node.name))
    fr = link.to_socket.path_from_id()
    fr = fr.split(".")

    if len(fr) == 3:
        fr = fr[2]
    else:
        fr = fr[1]

    n1 = fr.index("[")
    n2 = fr.index("]")
    ind = int(fr[n1 + 1:n2])
    out.append(ind)

    return out


def export_material(self, context):
    mat_list = []
    export_type = context.scene.material_io_export_type
    export_path = bpy.path.abspath(context.scene.material_io_export_path)
    folder_path = None
    folder_name = None

    # check file paths
    if not export_path:
        self.report({"ERROR"}, "Empty Export Path")
        return
    elif not path.exists(export_path):
        self.report({"ERROR"}, "Export Path '{}' Does Not Exist".format(export_path))
        return

    # determine what all is being exported and the name of the folder to export to
    if export_type == "1" and context.material is not None:
        mat_list.append(context.material.name)
    elif export_type == "2":
        folder_name = context.object.name
        for i in context.object.data.materials:
            mat_list.append(i.name)
    elif export_type == "3":
        folder_name = path.split(bpy.data.filepath)[1]
        for i in bpy.data.materials:
            mat_list.append(i.name)

    # create folder if more then 1 material, or if paths are being made relative
    if len(mat_list) > 1 or context.scene.material_io_image_save_type == "2":
        try:
            folder_path = export_path + os_file_sep + folder_name
            mkdir(folder_path)
        except FileExistsError:
            self.report({"ERROR"}, "Directory '{}' Already Exists, Cannot Continue".format(folder_path))
            return
    else:
        folder_path = export_path

    # export materials
    for mat_name in mat_list:
        # check render engine to see where nodes are located at
        if context.scene.render.engine in ("CYCLES", "BLENDER_RENDER"):
            mat = bpy.data.materials[mat_name]
        # mitsuba nodes are in a node group that is linked up to the material
        elif context.scene.render.engine == "MITSUBA_RENDER":
            if bpy.data.materials[mat_name].mitsuba_nodes.nodetree in bpy.data.node_groups:
                mat = bpy.data.node_groups[bpy.data.materials[mat_name].mitsuba_nodes.nodetree]
            else:
                mat = None
        
        if mat is not None:
            root = ET.Element("material")
            json_root = {}
            names = {}
            data, images = [], []
            m_links, m_nodes = [], []

            node_group_name = ""

            # main node and links sources depending on what render engine
            if context.scene.render.engine in ("CYCLES", "BLENDER_RENDER"):
                m_links = mat.node_tree.links
                m_nodes = mat.node_tree.nodes
            # mitsuba nodes are in a node group that is linked up to the material
            elif context.scene.render.engine == "MITSUBA_RENDER":
                m_links = mat.links
                m_nodes = mat.nodes
                node_group_name = bpy.data.materials[mat_name].mitsuba_nodes.nodetree

            # get node data
            collect_nodes(m_nodes, m_links, images, names, "main", data)

            # write data
            # material attribs
            t = datetime.now()
            date_string = "{}/{}/{} at {}:{}:{} in {}".format(t.month, t.day, t.year, t.hour, t.minute,
                                                              t.second, tzname[0])

            node_counter = 0
            for group in names:
                json_root[group] = {'nodes': data[names[group]][0], 'links': data[names[group]][1]}

            # get order of groups
            pre_order = sorted(names.items(), key=operator.itemgetter(1))
            order = [i[0].replace("/", "_") for i in pre_order]
            json_root['__info__'] = {'number_of_nodes': node_counter, 'group_order': order, "render_engine":
                                     context.scene.render.engine, "material_name": serialize(mat.name),
                                     "node_group_name": serialize(node_group_name), "date_created": date_string}

            # images
            img_out = []  # collect all images to place as attribute of root element so they can be imported first

            # absolute filepaths
            if context.scene.material_io_image_save_type == "1":
                json_root['__info__']['path_type'] = "absolute"

                # of format [node, node,...] where each node is [image, image,...] and image is [name, path]
                for node in images:
                    for image in node:
                        img_out.append([image[0], bpy.path.abspath(image[1])])
            else:  # relative filepaths
                json_root['__info__']['path_type'] = "relative"

                for node in images:
                    for image in node:
                        image_path = bpy.path.abspath(image[1])
                        image_name = path.split(image_path)[1]
                        img_out.append([image[0], os_file_sep + image_name])
                        copyfile(image_path, folder_path + os_file_sep + image_name)

            json_root['__info__']['images'] = img_out
            save_path = folder_path + os_file_sep + mat_name + ".bmat"

            try:
                file = open(save_path, 'w')
                json.dump(json_root, file)
                file.close()
            except (PermissionError, FileNotFoundError):
                self.report({"ERROR"}, "Permission Denied '{}'".format(save_path))
                return


    # zip folder
    if folder_path != export_path and context.scene.material_io_is_compress:  # if folder has been created
        if path.exists(folder_path + ".zip"):  # if zipped file is already there, delete
            remove_file(folder_path + ".zip")

        zf = zipfile.ZipFile(folder_path + ".zip", "w", zipfile.ZIP_DEFLATED)
        for dirname, subdirs, files in walk(folder_path):
            for filename in files:
                zf.write(path.join(dirname, filename), arcname=filename)
        zf.close()

        # delete non-compressed folder
        rmtree(folder_path)


def import_material(self, context):
    import_path = None
    folder_path = None  # use for getting images if needed

    if context.scene.material_io_import_type == "1":  # single file
        import_path = bpy.path.abspath(context.scene.material_io_import_path_file)
        folder_path = path.dirname(import_path)
    else:  # all files in folder
        import_path = bpy.path.abspath(context.scene.material_io_import_path_dir)
        folder_path = import_path

    # check file path
    if not import_path:
        self.report({"ERROR"}, "Empty Import Path")
        return
    elif not path.exists(import_path):
        self.report({"ERROR"}, "Filepath '{}' Does Not Exist".format(import_path))
        return
    elif context.scene.material_io_import_type == "1" and not import_path.endswith(".bmat"):
        self.report({"ERROR"}, "Filepath Does Not End With .bmat")
        return

    # collect filepaths
    import_list = []

    if context.scene.material_io_import_type == "2":  # import all files in folder
        files = listdir(import_path)

        for file in files:
            if file.endswith(".bmat"):
                import_list.append(import_path + os_file_sep + file)
    else:
        import_list.append(import_path)

    # for each .bmat file import and create material
    for file_path in import_list:
        tree = ET.parse(file_path)
        root = tree.getroot()
        mat = bpy.data.materials.new(root.attrib["Material_Name"])
        nodes = None
        links = None

        # make sure in correct render mode
        if root.attrib["Render_Engine"] != context.scene.render.engine:
            self.report({"ERROR"}, "Cannot Continue: Please Switch To '{}' Engine".format(root.attrib["Render_Engine"]))
            return

        # check and see render engine data
        if root.attrib["Render_Engine"] in ("BLENDER_RENDER", "CYCLES"):
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links
            context.scene.render.engine = root.attrib["Render_Engine"]
        elif root.attrib["Render_Engine"] == "MITSUBA_RENDER" and context.scene.render.engine == "MITSUBA_RENDER":
            node_group = bpy.data.node_groups.new(name=root.attrib["Node_Group_Name"], type="MitsubaShaderNodeTree")
            nodes = node_group.nodes
            links = node_group.links
            mat.mitsuba_nodes.nodetree = node_group.name

        # remove any default nodes
        for i in nodes:
            nodes.remove(i)

        # import images
        images = ast.literal_eval(root.attrib["Images"])
        image_errors = 0

        # don't load image if Render_Engine is MITSUBA_RENDER because it uses absolute file paths
        if root.attrib["Render_Engine"] != "MITSUBA_RENDER":
            for image in images:
                if image[0] not in bpy.data.images:
                    try:
                        if root.attrib["Path_Type"] == "Relative":
                            bpy.data.images.load(folder_path + os_file_sep + image[0])
                        else:
                            bpy.data.images.load(image[1])
                    except RuntimeError:
                        image_errors += 1

            if image_errors:
                self.report({"ERROR"}, str(image_errors) + " Picture(s) Couldn't Be Loaded")

        # add new nodes
        order = ast.literal_eval(root.attrib["Group_Order"])
        for group_order in order:
            group = root.findall(group_order)[0]

            # set up which node tree to use
            if group.tag == "main":
                nt = nodes
            else:
                nt = bpy.data.node_groups.new(group.tag, "ShaderNodeTree")

            is_nodes = True  # nodes or links
            for data in group:
                if is_nodes:  # nodes
                    parents = []

                    for node in data:
                        parent = []

                        # check if node is custom then make sure it is installed
                        if node.attrib["bl_idname"] == "GenericNoteNode" and \
                                ("generic_note" not in bpy.context.user_preferences.addons.keys() and
                                 "genericnote" not in bpy.context.user_preferences.addons.keys()):

                            self.report({"WARNING"}, "Generic Note Node Add-on Not Installed")
                        else:
                            # retrieve node name, create node
                            if group.tag != "main":
                                temp = nt.nodes.new(node.attrib["bl_idname"])
                            else:
                                temp = nt.new(node.attrib["bl_idname"])

                            # node specific is first so that groups are set up first
                            nos = node.attrib["node_specific"]
                            if nos:
                                nod = ast.literal_eval(nos)
                                for i in range(0, len(nod), 2):  # step by two because name, value, name, value...
                                    att = nod[i]
                                    val = nod[i + 1]

                                    # group node inputs and outputs
                                    if att in ("group_input", "group_output"):
                                        for sub in range(0, len(val), 2):
                                            sub_val = [val[sub], val[sub + 1]]
                                            if att == "group_input":
                                                nt.inputs.new(sub_val[0], sub_val[1])
                                            else:
                                                nt.outputs.new(sub_val[0], sub_val[1])
                                    elif att == "parent" and val is not None:
                                        parent.append(val)
                                    elif val is not None:
                                        set_attributes(temp, val, att)

                            # inputs
                            ins = node.attrib["inputs"]
                            if ins != "":
                                inp = ast.literal_eval(ins)
                                for i in range(0, len(inp), 2):
                                    if inp[i + 1] != "SHADER":
                                        temp.inputs[inp[i]].default_value = inp[i + 1]
                            # outputs
                            ous = node.attrib["outputs"]
                            if ous != "":
                                out = ast.literal_eval(ous)
                                for i in range(0, len(out), 2):
                                    temp.outputs[out[i]].default_value = out[i + 1]

                            # deal with parent
                            if parent:
                                parent += [temp.name, temp.location]
                                parents.append(parent)

                    # TODO: Fix parent and child location issues
                    # set parents
                    for parent in parents:
                        print(parent)
                        if group.tag != "main":
                            nt.nodes[parent[1]].parent = nt.nodes[parent[0]]
                            nt.nodes[parent[1]].location = parent[2]
                        else:
                            nt[parent[1]].parent = nt[parent[0]]
                            nt[parent[1]].location = parent[2]

                # create links
                else:
                    for link in data:
                        ld = ast.literal_eval(link.attrib["link_info"])
                        if group.tag == "main":
                            o = nt[ld[0]].outputs[ld[1]]
                            i = nt[ld[2]].inputs[ld[3]]
                            links.new(o, i)
                        else:
                            o = nt.nodes[ld[0]].outputs[ld[1]]
                            i = nt.nodes[ld[2]].inputs[ld[3]]
                            nt.links.new(o, i)

                is_nodes = not is_nodes

        if root.attrib["Render_Engine"] != "MITSUBA_RENDER":
            # get rid of extra groups
            for i in bpy.data.node_groups:
                if i.users == 0:
                    bpy.data.node_groups.remove(i)

        # add material to object
        if context.object is not None and context.scene.material_io_is_auto_add:
            context.object.data.materials.append(mat)


def s_to_t(s):
    tu = s.split(", ")
    tu[0] = tu[0].replace("(", "")
    tu[len(tu) - 1] = tu[len(tu) - 1].replace(")", "")

    return [float(i) for i in tu]


def set_attributes(temp, val, att):
    # determine attribute type, exec() can be used if value gets directly set to attribute
    if att == "image" and val in bpy.data.images:
        temp.image = bpy.data.images[val]
    elif att == "object" and val in bpy.data.objects:
        temp.object = bpy.data.objects[val]
    elif att == "particle_system" and val[0] in bpy.data.objects \
            and val[1] in bpy.data.objects[val[0]].particle_systems:
        temp.particle_system = bpy.data.objects[val[0]].particle_systems[val[1]]
    elif att == "color_ramp.elements":
        e = temp.color_ramp.elements
        if len(val) >= 2:
            e[0].position = val[0][0]
            e[0].color = val[0][1]
            e[1].position = val[1][0]
            e[1].color = val[1][1]
            del val[0:2]
        for el in val:
            e_temp = e.new(el[0])
            e_temp.color = el[1]
    elif att == "node_tree.name":
        temp.node_tree = bpy.data.node_groups[val]
    elif att == "material":
        try:
            temp.material = bpy.data.materials[val]
        except KeyError:
            pass
    elif att == "mapping":
        # set curves
        temp.mapping.black_level = val[0]
        temp.mapping.white_level = val[1]
        temp.mapping.clip_max_x = float(val[2])
        temp.mapping.clip_max_y = float(val[3])
        temp.mapping.clip_min_x = float(val[4])
        temp.mapping.clip_min_y = float(val[5])
        temp.mapping.use_clip = True if val[6] == "True" else False

        for i in range(7):
            del val[0]

        # go through each curve
        counter = 0
        for i in val:
            # set first two points
            curves = temp.mapping.curves
            curves[counter].extend = i[0]
            del i[0]
            curves[counter].points[0].location = i[0][0]
            curves[counter].points[0].handle_type = i[0][1]
            curves[counter].points[1].location = i[1][0]
            curves[counter].points[1].handle_type = i[1][1]
            del i[0:2]
            for i2 in i:
                temp_point = temp.mapping.curves[counter].points.new(i2[0][0], i2[0][1])
                temp_point.handle_type = i2[1]
            counter += 1
    else:
        if isinstance(val, str):
            exec("temp.{} = '{}'".format(att, val))
        else:
            exec("temp.{} = {}".format(att, val))

# PROPERTIES
bpy.types.Scene.material_io_import_export = EnumProperty(name="Import/Export", items=(("1", "Import", ""),
                                                                                      ("2", "Export", "")))
bpy.types.Scene.material_io_export_path = StringProperty(name="Export Path", subtype="DIR_PATH")
bpy.types.Scene.material_io_import_path_file = StringProperty(name="Import Path", subtype="FILE_PATH")
bpy.types.Scene.material_io_import_path_dir = StringProperty(name="Import Path", subtype="DIR_PATH")
bpy.types.Scene.material_io_image_save_type = EnumProperty(name="Image Path", items=(("1", "Absolute Paths", ""),
                                                                                     ("2", "Make Paths Relative", "")),
                                                           default="1")
bpy.types.Scene.material_io_is_auto_add = BoolProperty(name="Add Material To Object?", default=True)
bpy.types.Scene.material_io_export_type = EnumProperty(name="Export Type", items=(("1", "Selected", ""),
                                                                                  ("2", "Current Object", ""),
                                                                                  ("3", "All Materials", "")))
bpy.types.Scene.material_io_import_type = EnumProperty(name="Import Type", items=(("1", "Single", ""),
                                                                                  ("2", "Multiple", "")))
bpy.types.Scene.material_io_is_compress = BoolProperty(name="Compress Folder?")


class MaterialIOPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_material_io_panel"
    bl_label = "Material IO Panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_category = "material"
    bl_context = "material"       
    
    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "material_io_import_export")
        layout.separator()
        
        if context.scene.material_io_import_export == "2":
            layout.prop(context.scene, "material_io_export_type")
            layout.prop(context.scene, "material_io_image_save_type")
            layout.prop(context.scene, "material_io_is_compress", icon="FILTER")
            layout.separator()
            layout.prop(context.scene, "material_io_export_path")
            layout.separator()
            layout.operator("export.material_io_export", icon="ZOOMOUT")
                  
        else:
            layout.prop(context.scene, "material_io_import_type")
            layout.prop(context.scene, "material_io_is_auto_add", icon="MATERIAL")
            layout.separator()

            if context.scene.material_io_import_type == "1":
                layout.prop(context.scene, "material_io_import_path_file")
            else:
                layout.prop(context.scene, "material_io_import_path_dir")
            layout.separator()

            layout.operator("import.material_io_import", icon="ZOOMIN")


class MaterialIOExport(bpy.types.Operator):
    bl_idname = "export.material_io_export"
    bl_label = "Export Material"
    
    def execute(self, context):
        export_material(self, context)
        return {"FINISHED"}


class MaterialIOImport(bpy.types.Operator):
    bl_idname = "import.material_io_import"
    bl_label = "Import Material"
    
    def execute(self, context):
        import_material(self, context)
        return {"FINISHED"}             


def register():
    bpy.utils.register_module(__name__)


def unregister():
    bpy.utils.unregister_module(__name__)

if __name__ == "__main__":
    register()
