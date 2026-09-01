import re
import struct
import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty

VERSION_NAMES = {
    b'1.00': '1.00', b'1.01': '1.01', b'2.00': '2.00', b'3.00': '3.00',
    b'3.01': '3.01', b'4.00': '4.00', b'4.01': '4.01', b'5.00': '5.00',
    b'6.00': '6.00', b'7.00': '7.00'
}


def _name(filepath):
    return filepath.rsplit('/', 1)[-1].rsplit('\\', 1)[-1].rsplit('.', 1)[0]


def detect_version(data):
    if len(data) < 12 or not data.startswith(b'version '):
        raise ValueError('Not a Roblox FileMesh: missing version header.')
    raw = data[8:12]
    if raw not in VERSION_NAMES:
        raise ValueError('Unsupported Roblox mesh version: ' + raw.decode('ascii', 'replace'))
    return VERSION_NAMES[raw]


def _parse_v1(data, scale, flip_uv):
    text = data.decode('ascii', 'strict')
    lines = text.splitlines()
    if len(lines) < 3:
        raise ValueError('Roblox V1 mesh is missing its face data.')
    try:
        faces_count = int(lines[1].strip())
    except ValueError:
        raise ValueError('Invalid V1 face count.')
    payload = ''.join(lines[2:])
    nums = re.findall(r'\[\s*([^\]]+)\]', payload)
    if len(nums) < faces_count * 9:
        raise ValueError(f'V1 mesh contains {len(nums)} vectors; expected {faces_count * 9}.')
    verts, normals, uvs, faces = [], [], [], []
    for face_i in range(faces_count):
        ids = []
        for corner in range(3):
            base = (face_i * 9) + corner * 3
            try:
                p = [float(x.strip()) for x in nums[base].split(',')]
                n = [float(x.strip()) for x in nums[base + 1].split(',')]
                uv = [float(x.strip()) for x in nums[base + 2].split(',')]
            except Exception as exc:
                raise ValueError(f'Invalid V1 vertex data near face {face_i + 1}.') from exc
            if len(p) < 3 or len(n) < 3 or len(uv) < 2:
                raise ValueError('Invalid V1 vector.')
            verts.append(tuple(v * scale for v in p[:3]))
            normals.append(tuple(n[:3]))
            uvs.append((uv[0], 1.0 - uv[1] if flip_uv else uv[1]))
            ids.append(len(verts) - 1)
        faces.append(tuple(ids))
    return verts, faces, normals, uvs


def _read_v2_header(data, offset):
    if len(data) < offset + 12:
        raise ValueError('Roblox V2/V3 header is truncated.')
    header_size, vert_size, face_size, num_verts, num_faces = struct.unpack_from('<HBBII', data, offset)
    return header_size, vert_size, face_size, num_verts, num_faces, offset + 12


def _parse_v2_or_v3(data, scale, version):
    # Version 2 has a 12-byte binary header after the text header.
    # V3 adds 4 bytes for LOD metadata to that header.
    off = 13
    if len(data) >= 17 and data[12] in (0x0A, 0x0D):
        off = 13 if data[12] == 0x0A else (15 if data[12:14] == b'\r\n' else 14)
    header_size, vert_size, face_size, nv, nf, off = _read_v2_header(data, off)
    if version in ('3.00', '3.01'):
        if header_size < 16 or len(data) < off + 4:
            raise ValueError('Invalid V3 header.')
        lod_size, lod_count = struct.unpack_from('<HH', data, off)
        off += 4
    if nv <= 0 or nf <= 0:
        raise ValueError('Roblox mesh contains no geometry.')
    if vert_size not in (36, 40):
        raise ValueError(f'Unsupported Roblox V{version} vertex size: {vert_size}.')
    if face_size not in (12,):
        raise ValueError(f'Unsupported Roblox V{version} face size: {face_size}.')
    needed = off + nv * vert_size + nf * face_size
    if len(data) < needed:
        raise ValueError('Roblox binary mesh is truncated.')
    verts, normals, uvs = [], [], []
    for _ in range(nv):
        px, py, pz, nx, ny, nz, tu, tv = struct.unpack_from('<8f', data, off)
        off += 32
        # tangent/binormal direction and optional RGBA are deliberately ignored
        off += vert_size - 32
        verts.append((px * scale, py * scale, pz * scale))
        normals.append((nx, ny, nz))
        uvs.append((tu, tv))
    faces = []
    for _ in range(nf):
        faces.append(struct.unpack_from('<3I', data, off))
        off += face_size
    return verts, faces, normals, uvs


def _make_object(filepath, context, verts, faces, normals, uvs, version):
    name = _name(filepath)
    me = bpy.data.meshes.new(name + 'Mesh')
    me.from_pydata(verts, [], faces)
    me.update()
    obj = bpy.data.objects.new(name, me)
    context.collection.objects.link(obj)
    if normals and len(normals) == len(me.vertices):
        for poly in me.polygons:
            for li in poly.loop_indices:
                vi = me.loops[li].vertex_index
                try:
                    me.vertices[vi].normal = normals[vi]
                except Exception:
                    pass
    if uvs and len(uvs) == len(me.vertices):
        layer = me.uv_layers.new(name='UVMap')
        for poly in me.polygons:
            for li in poly.loop_indices:
                vi = me.loops[li].vertex_index
                layer.data[li].uv = uvs[vi]
    obj['MeshBridge_format'] = 'Roblox FileMesh'
    obj['MeshBridge_version'] = version
    for old in context.selected_objects:
        old.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def read_roblox_mesh(filepath, context, target_scale=1.0):
    with open(filepath, 'rb') as f:
        data = f.read()
    version = detect_version(data)
    if version == '1.00':
        verts, faces, normals, uvs = _parse_v1(data, 0.5 * target_scale, True)
    elif version == '1.01':
        verts, faces, normals, uvs = _parse_v1(data, target_scale, True)
    elif version in ('2.00', '3.00', '3.01'):
        verts, faces, normals, uvs = _parse_v2_or_v3(data, target_scale, version)
    else:
        raise ValueError(f'Roblox mesh {version} is detected, but this build does not yet decode its skeletal/LOD schema.')
    return _make_object(filepath, context, verts, faces, normals, uvs, version)


def _triangles(obj):
    me = obj.data
    tris = []
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(1, len(vs) - 1):
            tris.append((vs[0], vs[i], vs[i + 1]))
    return tris


def write_v1(filepath, obj, version='1.01'):
    me = obj.data
    tris = _triangles(obj)
    with open(filepath, 'w', encoding='ascii', newline='\n') as f:
        f.write('version ' + version + '\n')
        f.write(str(len(tris)) + '\n')
        for a, b, c in tris:
            for vi in (a, b, c):
                v = me.vertices[vi].co
                n = me.vertices[vi].normal
                uv = (0.0, 0.0)
                if me.uv_layers.active:
                    # Use the first loop using this vertex; V1 stores UV per corner,
                    # so this is intentionally a simple static-mesh export path.
                    for poly in me.polygons:
                        for li in poly.loop_indices:
                            if me.loops[li].vertex_index == vi:
                                uv = tuple(me.uv_layers.active.data[li].uv)
                                break
                        else:
                            continue
                        break
                y = 1.0 - uv[1]
                scale = 2.0 if version == '1.00' else 1.0
                p = (v.x * scale, v.y * scale, v.z * scale)
                f.write('[%.9g,%.9g,%.9g][%.9g,%.9g,%.9g][%.9g,%.9g,0]\n' % (*p, *n, uv[0], y))


def write_v2(filepath, obj):
    me = obj.data
    tris = _triangles(obj)
    verts = []
    # Keep a stable per-Blender-vertex representation; this is compact and valid
    # for static geometry, although it does not attempt Roblox's optional tangents.
    for v in me.vertices:
        uv = (0.0, 0.0)
        if me.uv_layers.active:
            for poly in me.polygons:
                found = False
                for li in poly.loop_indices:
                    if me.loops[li].vertex_index == v.index:
                        uv = tuple(me.uv_layers.active.data[li].uv); found = True; break
                if found: break
        verts.append((v.co.x, v.co.y, v.co.z, v.normal.x, v.normal.y, v.normal.z, uv[0], uv[1]))
    with open(filepath, 'wb') as f:
        f.write(b'version 2.00\n')
        f.write(struct.pack('<HBBII', 12, 36, 12, len(verts), len(tris)))
        for rec in verts:
            f.write(struct.pack('<8f', *rec))
            f.write(b'\x00\x00\x00\x00')
        for a, b, c in tris:
            f.write(struct.pack('<3I', a, b, c))


class IMPORT_OT_nostro(Operator, ImportHelper):
    bl_idname = 'meshbridge.import_nostro'
    bl_label = 'Import Roblox Mesh'
    filename_ext = '.mesh'
    filter_glob: StringProperty(default='*.mesh', options={'HIDDEN'})

    def execute(self, context):
        try:
            obj = read_roblox_mesh(self.filepath, context, context.scene.meshbridge.import_scale)
            s = context.scene.meshbridge
            if s.frame_imported and context.area and context.area.type == 'VIEW_3D':
                bpy.ops.view3d.view_selected(use_all_regions=False)
            self.report({'INFO'}, f'Imported Roblox Mesh v{obj["MeshBridge_version"]}.')
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class EXPORT_OT_nostro(Operator, ExportHelper):
    bl_idname = 'meshbridge.export_nostro'
    bl_label = 'Export Roblox Mesh'
    filename_ext = '.mesh'
    filter_glob: StringProperty(default='*.mesh', options={'HIDDEN'})
    version: EnumProperty(
        name='Roblox Mesh Version',
        items=[('1.00','1.00','Legacy ASCII'),('1.01','1.01','ASCII without the V1.00 scale quirk'),('2.00','2.00','Binary static mesh')],
        default='2.00'
    )

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, 'Select a mesh object.')
            return {'CANCELLED'}
        try:
            if self.version in ('1.00', '1.01'):
                write_v1(self.filepath, obj, self.version)
            else:
                write_v2(self.filepath, obj)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Exported Roblox Mesh v{self.version}.')
        return {'FINISHED'}


classes = (IMPORT_OT_nostro, EXPORT_OT_nostro)

def register():
    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
